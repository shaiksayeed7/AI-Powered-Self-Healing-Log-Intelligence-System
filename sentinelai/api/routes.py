"""FastAPI route definitions for SentinelAI."""

from __future__ import annotations

import asyncio
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel

from sentinelai.analysis.fix_suggester import FixSuggester
from sentinelai.analysis.rca_engine import RCAEngine
from sentinelai.detection.anomaly_detector import AnomalyDetector
from sentinelai.detection.predictor import FailurePredictor
from sentinelai.log_ingestion.parser import parse_log_line
from sentinelai.log_ingestion.streamer import stream_file_from_start
from sentinelai.storage.database import Database

router = APIRouter()
db = Database()
rca_engine = RCAEngine()
fix_suggester = FixSuggester()

# Per-service stateful detectors
_detectors: dict[str, AnomalyDetector] = {}
_predictors: dict[str, FailurePredictor] = {}


def _get_detector(service: str) -> AnomalyDetector:
    if service not in _detectors:
        _detectors[service] = AnomalyDetector()
    return _detectors[service]


def _get_predictor(service: str) -> FailurePredictor:
    if service not in _predictors:
        _predictors[service] = FailurePredictor()
    return _predictors[service]


# ── Pydantic models ───────────────────────────────────────────────────────────

class LogLineInput(BaseModel):
    line: str


class IngestFileInput(BaseModel):
    path: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/health")
def health():
    """Simple health-check endpoint."""
    return {"status": "ok", "service": "SentinelAI"}


@router.post("/ingest/line")
def ingest_line(payload: LogLineInput):
    """Parse a single raw log line and run detection pipeline."""
    record = parse_log_line(payload.line)
    if record is None:
        raise HTTPException(status_code=422, detail="Could not parse log line.")

    db.insert_log(record)
    service = record.get("service", "unknown")
    detector = _get_detector(service)
    predictor = _get_predictor(service)

    detector.ingest(record)
    anomaly = detector.check(service)
    if anomaly:
        db.insert_anomaly(service, anomaly)

    # Feed error rate to predictor (simplified: 1 error = error_rate=1, else 0)
    error_rate = 1.0 if record.get("level") in ("ERROR", "CRITICAL", "FATAL") else 0.0
    predictor.record(error_rate)
    prediction = predictor.predict()
    if prediction:
        db.insert_prediction(service, prediction)

    return {
        "record": record,
        "anomaly": vars(anomaly) if anomaly else None,
        "prediction": vars(prediction) if prediction else None,
    }


@router.post("/ingest/file")
async def ingest_file(payload: IngestFileInput, background_tasks: BackgroundTasks):
    """Parse an existing log file from start and return summary stats."""
    records_processed = 0
    error_codes: List[str] = []
    messages: List[str] = []

    async for record in stream_file_from_start(payload.path):
        db.insert_log(record)
        service = record.get("service", "unknown")
        detector = _get_detector(service)
        detector.ingest(record)
        if record.get("error_code"):
            error_codes.append(record["error_code"])
        if record.get("message"):
            messages.append(record["message"])
        records_processed += 1

    rca = rca_engine.analyse(error_codes, messages) if error_codes else None
    fix = None
    if rca:
        fix = fix_suggester.suggest(rca.category, service)

    return {
        "records_processed": records_processed,
        "rca": vars(rca) if rca else None,
        "fix_suggestion": {
            "summary": fix.summary(),
            "actions": [vars(a) for a in fix.actions],
        } if fix else None,
    }


@router.get("/logs")
def get_logs(
    service: Optional[str] = Query(None),
    level: Optional[str] = Query(None),
    limit: int = Query(100, le=1000),
):
    """Retrieve stored log records."""
    return db.get_logs(service=service, level=level, limit=limit)


@router.get("/anomalies")
def get_anomalies(limit: int = Query(50, le=500)):
    """Retrieve stored anomaly events."""
    return db.get_anomalies(limit=limit)


@router.get("/predictions")
def get_predictions(limit: int = Query(50, le=500)):
    """Retrieve stored failure predictions."""
    return db.get_predictions(limit=limit)


@router.get("/rca")
def get_rca_results(limit: int = Query(50, le=500)):
    """Retrieve stored RCA results."""
    return db.get_rca_results(limit=limit)


@router.post("/analyse")
def analyse(
    error_codes: List[str],
    messages: Optional[List[str]] = None,
    service: str = "unknown",
):
    """Run RCA + fix suggestion on a supplied list of error codes."""
    rca = rca_engine.analyse(error_codes, messages)
    if rca is None:
        return {"rca": None, "fix_suggestion": None}
    db.insert_rca(service, rca)
    fix = fix_suggester.suggest(rca.category, service)
    return {
        "rca": vars(rca),
        "fix_suggestion": {
            "summary": fix.summary(),
            "actions": [vars(a) for a in fix.actions],
        },
    }
