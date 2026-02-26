"""FastAPI entry point for SentinelAI."""
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import config
from src.storage.database import DatabaseManager
from src.parser.log_parser import LogParser
from src.anomaly_detection.detector import AnomalyDetector
from src.prediction.failure_predictor import FailurePredictor
from src.rca.root_cause import RootCauseAnalyzer
from src.autofix.fix_suggester import FixSuggester
from src.log_ingestion.file_watcher import LogFileWatcher

logger = logging.getLogger("sentinelai")
logging.basicConfig(level=logging.INFO)

# --- Shared singletons ---
db = DatabaseManager(config.DB_PATH)
parser = LogParser()
detector = AnomalyDetector(window_size=config.WINDOW_SIZE, z_threshold=config.ANOMALY_THRESHOLD)
predictor = FailurePredictor()
rca = RootCauseAnalyzer()
suggester = FixSuggester()

_ws_clients: List[WebSocket] = []
_watcher: Optional[LogFileWatcher] = None


# ------------------------------------------------------------------
def _process_lines(lines: List[str]) -> None:
    """Parse, detect, predict and persist a batch of raw log lines."""
    entries = []
    for line in lines:
        entry = parser.parse(line)
        if entry:
            entries.append(entry)
            detector.add_log_entry(entry)
            predictor.update(entry)
            try:
                db.save_log_entry(entry)
            except Exception as exc:
                logger.warning("DB save_log_entry failed: %s", exc)

    if entries:
        anomalies = detector.detect_anomalies(entries)
        for a in anomalies:
            try:
                db.save_anomaly(a)
            except Exception as exc:
                logger.warning("DB save_anomaly failed: %s", exc)

        prediction = predictor.predict_failure()
        if prediction.get("predicted"):
            try:
                db.save_prediction(prediction)
            except Exception as exc:
                logger.warning("DB save_prediction failed: %s", exc)

        # Broadcast to WebSocket clients
        if _ws_clients:
            payload = json.dumps({"entries": entries, "anomalies": anomalies})
            asyncio.get_event_loop().create_task(_broadcast(payload))


async def _broadcast(message: str) -> None:
    dead = []
    for ws in list(_ws_clients):
        try:
            await ws.send_text(message)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _ws_clients.remove(ws)


# ------------------------------------------------------------------
@asynccontextmanager
async def lifespan(application: FastAPI):
    global _watcher
    # Seed existing log file on startup
    try:
        with open(config.LOG_FILE_PATH, "r", encoding="utf-8", errors="replace") as fh:
            lines = [l.rstrip("\n") for l in fh if l.strip()]
        _process_lines(lines)
    except FileNotFoundError:
        logger.info("Log file not found at startup; will wait for it.")

    def _callback(new_lines: List[str]):
        _process_lines(new_lines)

    _watcher = LogFileWatcher(config.LOG_FILE_PATH, _callback)
    _watcher.start()
    logger.info("Log file watcher started.")
    yield
    if _watcher:
        _watcher.stop()


app = FastAPI(title="SentinelAI", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok", "service": "SentinelAI"}


@app.get("/logs")
def get_logs(limit: int = Query(100, ge=1, le=1000), service: Optional[str] = None):
    return db.get_recent_logs(limit=limit, service=service)


@app.get("/anomalies")
def get_anomalies(limit: int = Query(50, ge=1, le=500)):
    return db.get_recent_anomalies(limit=limit)


@app.get("/predictions")
def get_predictions():
    return db.get_predictions()


class AnalyzeRequest(BaseModel):
    log_text: str


@app.post("/analyze")
def analyze(req: AnalyzeRequest):
    lines = [l for l in req.log_text.splitlines() if l.strip()]
    entries = [e for line in lines if (e := parser.parse(line)) is not None]
    if not entries:
        raise HTTPException(status_code=400, detail="No parseable log lines found.")

    local_detector = AnomalyDetector(window_size=config.WINDOW_SIZE, z_threshold=config.ANOMALY_THRESHOLD)
    local_predictor = FailurePredictor()
    for e in entries:
        local_detector.add_log_entry(e)
        local_predictor.update(e)

    anomalies = local_detector.detect_anomalies(entries)
    prediction = local_predictor.predict_failure()
    rca_result = rca.analyze(anomalies, entries)
    fixes = suggester.suggest_fixes(rca_result, anomalies)

    return {
        "parsed_entries": len(entries),
        "anomalies": anomalies,
        "prediction": prediction,
        "rca": rca_result,
        "fixes": fixes,
    }


@app.get("/dashboard/stats")
def dashboard_stats():
    logs = db.get_recent_logs(limit=200)
    anomalies = db.get_recent_anomalies(limit=50)
    predictions = db.get_predictions(limit=5)
    error_count = sum(1 for l in logs if l.get("level") in ("ERROR", "CRITICAL"))
    error_rate = error_count / max(len(logs), 1)
    return {
        "total_logs": len(logs),
        "error_rate": round(error_rate, 4),
        "active_anomalies": len(anomalies),
        "predictions": len([p for p in predictions if p.get("confidence", 0) > 0.3]),
        "services": list({l.get("service") for l in logs if l.get("service")}),
    }


@app.websocket("/ws/logs")
async def ws_logs(websocket: WebSocket):
    await websocket.accept()
    _ws_clients.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in _ws_clients:
            _ws_clients.remove(websocket)
