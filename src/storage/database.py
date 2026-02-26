"""SQLAlchemy models and CRUD operations for SentinelAI."""
import json
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import Column, Integer, String, Float, Text, DateTime, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session

Base = declarative_base()


class LogEntry(Base):
    __tablename__ = "log_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(String(50))
    level = Column(String(20))
    service = Column(String(100))
    message = Column(Text)
    error_type = Column(String(100), nullable=True)
    latency_ms = Column(Integer, nullable=True)
    raw = Column(Text)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class AnomalyEvent(Base):
    __tablename__ = "anomaly_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    type = Column(String(50))
    severity = Column(String(20))
    service = Column(String(100))
    description = Column(Text)
    timestamp = Column(String(50))
    metrics_json = Column(Text)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class PredictionEvent(Base):
    __tablename__ = "prediction_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    service = Column(String(100))
    time_to_failure_minutes = Column(Integer, nullable=True)
    confidence = Column(Float)
    cause = Column(String(200))
    indicators_json = Column(Text)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class DatabaseManager:
    """Manages all database interactions."""

    def __init__(self, db_url: str):
        self._engine = create_engine(db_url, connect_args={"check_same_thread": False})
        Base.metadata.create_all(self._engine)
        self._Session = sessionmaker(bind=self._engine)

    def _session(self) -> Session:
        return self._Session()

    # ------------------------------------------------------------------
    def save_log_entry(self, log_entry: dict) -> None:
        with self._session() as session:
            row = LogEntry(
                timestamp=log_entry.get("timestamp"),
                level=log_entry.get("level"),
                service=log_entry.get("service"),
                message=log_entry.get("message"),
                error_type=log_entry.get("error_type"),
                latency_ms=log_entry.get("latency_ms"),
                raw=log_entry.get("raw"),
            )
            session.add(row)
            session.commit()

    def save_anomaly(self, anomaly: dict) -> None:
        with self._session() as session:
            row = AnomalyEvent(
                type=anomaly.get("type"),
                severity=anomaly.get("severity"),
                service=anomaly.get("service"),
                description=anomaly.get("description"),
                timestamp=anomaly.get("timestamp"),
                metrics_json=json.dumps(anomaly.get("metrics", {})),
            )
            session.add(row)
            session.commit()

    def save_prediction(self, prediction: dict) -> None:
        with self._session() as session:
            row = PredictionEvent(
                service=prediction.get("service"),
                time_to_failure_minutes=prediction.get("time_to_failure_minutes"),
                confidence=prediction.get("confidence", 0.0),
                cause=prediction.get("cause"),
                indicators_json=json.dumps(prediction.get("indicators", [])),
            )
            session.add(row)
            session.commit()

    def get_recent_logs(self, limit: int = 100, service: Optional[str] = None) -> List[dict]:
        with self._session() as session:
            q = session.query(LogEntry).order_by(LogEntry.id.desc())
            if service:
                q = q.filter(LogEntry.service == service)
            rows = q.limit(limit).all()
        return [_log_row_to_dict(r) for r in reversed(rows)]

    def get_recent_anomalies(self, limit: int = 50) -> List[dict]:
        with self._session() as session:
            rows = session.query(AnomalyEvent).order_by(AnomalyEvent.id.desc()).limit(limit).all()
        return [_anomaly_row_to_dict(r) for r in reversed(rows)]

    def get_predictions(self, limit: int = 10) -> List[dict]:
        with self._session() as session:
            rows = session.query(PredictionEvent).order_by(PredictionEvent.id.desc()).limit(limit).all()
        return [_prediction_row_to_dict(r) for r in reversed(rows)]


def _log_row_to_dict(r: LogEntry) -> dict:
    return {
        "id": r.id, "timestamp": r.timestamp, "level": r.level,
        "service": r.service, "message": r.message,
        "error_type": r.error_type, "latency_ms": r.latency_ms,
        "raw": r.raw, "created_at": str(r.created_at),
    }


def _anomaly_row_to_dict(r: AnomalyEvent) -> dict:
    try:
        metrics = json.loads(r.metrics_json or "{}")
    except Exception:
        metrics = {}
    return {
        "id": r.id, "type": r.type, "severity": r.severity,
        "service": r.service, "description": r.description,
        "timestamp": r.timestamp, "metrics": metrics,
        "created_at": str(r.created_at),
    }


def _prediction_row_to_dict(r: PredictionEvent) -> dict:
    try:
        indicators = json.loads(r.indicators_json or "[]")
    except Exception:
        indicators = []
    return {
        "id": r.id, "service": r.service,
        "time_to_failure_minutes": r.time_to_failure_minutes,
        "confidence": r.confidence, "cause": r.cause,
        "indicators": indicators, "created_at": str(r.created_at),
    }
