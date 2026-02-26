"""
SentinelAI – FastAPI application entry point.

Endpoints
---------
POST /api/logs/ingest          – ingest a single raw log line
POST /api/logs/batch           – ingest a batch of raw log lines
GET  /api/anomalies            – list recent anomalies
GET  /api/predictions          – list recent predictions
GET  /api/rca/{service}        – run RCA on recent logs for a service
GET  /api/fix/{service}        – get fix suggestions for a service
GET  /api/logs                 – list recent ingested log entries
GET  /health                   – health check
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

import config
from analysis.fix_suggester import FixSuggester
from analysis.rca_engine import RCAEngine
from detection.anomaly_detector import AnomalyDetector
from detection.failure_predictor import FailurePredictor
from ingestion.log_parser import parse_line
from storage.database import (
    AsyncSessionLocal,
    get_recent_anomalies,
    get_recent_log_entries,
    get_recent_predictions,
    init_db,
    save_anomaly,
    save_log_entry,
    save_prediction,
    save_rca,
)


# ---------------------------------------------------------------------------
# Singletons (shared state)
# ---------------------------------------------------------------------------

anomaly_detector = AnomalyDetector()
failure_predictor = FailurePredictor()
rca_engine = RCAEngine()
fix_suggester = FixSuggester()


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="SentinelAI – Log Intelligence System",
    description="AI-powered self-healing log intelligence system.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Dependency
# ---------------------------------------------------------------------------

async def get_db() -> AsyncSession:  # type: ignore[return]
    async with AsyncSessionLocal() as session:
        yield session


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class IngestRequest(BaseModel):
    raw: str
    service: Optional[str] = None


class BatchIngestRequest(BaseModel):
    lines: list[str]
    service: Optional[str] = None


class IngestResponse(BaseModel):
    entry: dict
    anomaly: dict
    prediction: dict


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _process_line(
    raw: str,
    default_service: str,
    session: AsyncSession,
) -> dict[str, Any]:
    entry = parse_line(raw, default_service=default_service)
    entry_dict = entry.to_dict()
    entry_dict["raw"] = raw

    # Persist log entry
    await save_log_entry(session, entry_dict)

    # Anomaly detection
    anomaly_result = anomaly_detector.process(entry)
    anomaly_dict = anomaly_result.to_dict()
    if anomaly_result.is_anomaly:
        await save_anomaly(session, anomaly_dict)

    # Failure prediction
    pred_result = failure_predictor.process(entry)
    pred_dict = pred_result.to_dict()
    if pred_result.predicted_crash:
        await save_prediction(session, pred_dict)

    return {
        "entry": entry_dict,
        "anomaly": anomaly_dict,
        "prediction": pred_dict,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok", "service": "sentinelai"}


@app.post("/api/logs/ingest", response_model=IngestResponse)
async def ingest_log(
    req: IngestRequest,
    session: AsyncSession = Depends(get_db),
):
    default_service = req.service or "unknown"
    result = await _process_line(req.raw, default_service, session)
    return result


@app.post("/api/logs/batch")
async def ingest_batch(
    req: BatchIngestRequest,
    session: AsyncSession = Depends(get_db),
):
    default_service = req.service or "unknown"
    results = []
    for line in req.lines:
        if line.strip():
            r = await _process_line(line, default_service, session)
            results.append(r)
    return {"processed": len(results), "results": results}


@app.get("/api/logs")
async def list_logs(
    limit: int = Query(default=100, ge=1, le=1000),
    service: Optional[str] = Query(default=None),
    session: AsyncSession = Depends(get_db),
):
    records = await get_recent_log_entries(session, limit=limit, service=service)
    return {
        "count": len(records),
        "entries": [
            {
                "id": r.id,
                "timestamp": r.timestamp.isoformat(),
                "level": r.level,
                "service": r.service,
                "message": r.message,
                "error_type": r.error_type,
                "latency_ms": r.latency_ms,
            }
            for r in records
        ],
    }


@app.get("/api/anomalies")
async def list_anomalies(
    limit: int = Query(default=50, ge=1, le=500),
    session: AsyncSession = Depends(get_db),
):
    records = await get_recent_anomalies(session, limit=limit)
    return {
        "count": len(records),
        "anomalies": [
            {
                "id": r.id,
                "detected_at": r.detected_at.isoformat(),
                "service": r.service,
                "level": r.level,
                "message": r.message,
                "zscore": r.zscore,
                "isolation_score": r.isolation_score,
                "reason": r.reason,
            }
            for r in records
        ],
    }


@app.get("/api/predictions")
async def list_predictions(
    limit: int = Query(default=50, ge=1, le=500),
    session: AsyncSession = Depends(get_db),
):
    records = await get_recent_predictions(session, limit=limit)
    return {
        "count": len(records),
        "predictions": [
            {
                "id": r.id,
                "predicted_at": r.predicted_at.isoformat(),
                "service": r.service,
                "predicted_crash": r.predicted_crash,
                "confidence": r.confidence,
                "estimated_minutes": r.estimated_minutes,
                "cause": r.cause,
                "error_velocity_pct": r.error_velocity_pct,
            }
            for r in records
        ],
    }


@app.get("/api/rca/{service}")
async def run_rca(
    service: str,
    window: int = Query(default=100, ge=10, le=1000),
    session: AsyncSession = Depends(get_db),
):
    records = await get_recent_log_entries(session, limit=window, service=service)
    if not records:
        raise HTTPException(status_code=404, detail=f"No logs found for service '{service}'")

    # Reconstruct lightweight LogEntry objects from DB records
    from ingestion.log_parser import LogEntry
    from datetime import datetime

    entries = [
        LogEntry(
            raw=r.raw or "",
            timestamp=r.timestamp,
            level=r.level,
            service=r.service,
            message=r.message,
            error_type=r.error_type,
            latency_ms=r.latency_ms,
        )
        for r in records
    ]

    rca = rca_engine.analyse(entries)
    await save_rca(session, rca.to_dict(), service)
    return rca.to_dict()


@app.get("/api/fix/{service}")
async def get_fix(
    service: str,
    window: int = Query(default=100, ge=10, le=1000),
    session: AsyncSession = Depends(get_db),
):
    records = await get_recent_log_entries(session, limit=window, service=service)
    if not records:
        raise HTTPException(status_code=404, detail=f"No logs found for service '{service}'")

    from ingestion.log_parser import LogEntry

    entries = [
        LogEntry(
            raw=r.raw or "",
            timestamp=r.timestamp,
            level=r.level,
            service=r.service,
            message=r.message,
            error_type=r.error_type,
            latency_ms=r.latency_ms,
        )
        for r in records
    ]

    rca = rca_engine.analyse(entries)
    fix = fix_suggester.suggest(rca, service)
    return fix.to_dict()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=config.API_HOST,
        port=config.API_PORT,
        reload=False,
    )
