"""
Storage layer – SQLAlchemy async models and CRUD helpers backed by SQLite.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

import config


# ---------------------------------------------------------------------------
# Engine / session factory
# ---------------------------------------------------------------------------

engine = create_async_engine(config.DATABASE_URL, echo=False)

AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ---------------------------------------------------------------------------
# ORM models
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    pass


class LogEntryRecord(Base):
    __tablename__ = "log_entries"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    level = Column(String(16), index=True)
    service = Column(String(128), index=True)
    message = Column(Text)
    error_type = Column(String(128), nullable=True)
    latency_ms = Column(Float, nullable=True)
    raw = Column(Text)
    extra = Column(JSON, default=dict)


class AnomalyRecord(Base):
    __tablename__ = "anomalies"

    id = Column(Integer, primary_key=True, index=True)
    detected_at = Column(DateTime, default=datetime.utcnow, index=True)
    service = Column(String(128), index=True)
    level = Column(String(16))
    message = Column(Text)
    zscore = Column(Float, nullable=True)
    isolation_score = Column(Float, nullable=True)
    reason = Column(Text)


class PredictionRecord(Base):
    __tablename__ = "predictions"

    id = Column(Integer, primary_key=True, index=True)
    predicted_at = Column(DateTime, default=datetime.utcnow, index=True)
    service = Column(String(128), index=True)
    predicted_crash = Column(Boolean)
    confidence = Column(Float)
    estimated_minutes = Column(Integer, nullable=True)
    cause = Column(Text)
    error_velocity_pct = Column(Float)


class RCARecord(Base):
    __tablename__ = "rca_results"

    id = Column(Integer, primary_key=True, index=True)
    analysed_at = Column(DateTime, default=datetime.utcnow, index=True)
    service = Column(String(128), index=True)
    probable_cause = Column(Text, nullable=True)
    matched_rule = Column(String(64), nullable=True)
    signals = Column(JSON, default=list)
    confidence = Column(Float)


# ---------------------------------------------------------------------------
# DB initialisation
# ---------------------------------------------------------------------------

async def init_db() -> None:
    """Create all tables if they do not exist."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------

async def save_log_entry(session: AsyncSession, entry_dict: dict) -> LogEntryRecord:
    record = LogEntryRecord(
        timestamp=datetime.fromisoformat(entry_dict["timestamp"]),
        level=entry_dict["level"],
        service=entry_dict["service"],
        message=entry_dict["message"],
        error_type=entry_dict.get("error_type"),
        latency_ms=entry_dict.get("latency_ms"),
        raw=entry_dict.get("raw", ""),
        extra=entry_dict.get("extra", {}),
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record


async def save_anomaly(session: AsyncSession, anomaly_dict: dict) -> AnomalyRecord:
    record = AnomalyRecord(
        service=anomaly_dict["service"],
        level=anomaly_dict["level"],
        message=anomaly_dict["message"],
        zscore=anomaly_dict.get("zscore"),
        isolation_score=anomaly_dict.get("isolation_score"),
        reason=anomaly_dict.get("reason", ""),
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record


async def save_prediction(session: AsyncSession, pred_dict: dict) -> PredictionRecord:
    record = PredictionRecord(
        service=pred_dict["service"],
        predicted_crash=pred_dict["predicted_crash"],
        confidence=pred_dict["confidence"],
        estimated_minutes=pred_dict.get("estimated_minutes"),
        cause=pred_dict.get("cause", ""),
        error_velocity_pct=pred_dict.get("error_velocity_pct", 0.0),
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record


async def save_rca(session: AsyncSession, rca_dict: dict, service: str) -> RCARecord:
    record = RCARecord(
        service=service,
        probable_cause=rca_dict.get("probable_cause"),
        matched_rule=rca_dict.get("matched_rule"),
        signals=rca_dict.get("signals", []),
        confidence=rca_dict.get("confidence", 0.0),
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record


async def get_recent_anomalies(
    session: AsyncSession, limit: int = 50
) -> list[AnomalyRecord]:
    result = await session.execute(
        select(AnomalyRecord)
        .order_by(AnomalyRecord.detected_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_recent_predictions(
    session: AsyncSession, limit: int = 50
) -> list[PredictionRecord]:
    result = await session.execute(
        select(PredictionRecord)
        .order_by(PredictionRecord.predicted_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_recent_log_entries(
    session: AsyncSession, limit: int = 100, service: Optional[str] = None
) -> list[LogEntryRecord]:
    q = select(LogEntryRecord).order_by(LogEntryRecord.timestamp.desc()).limit(limit)
    if service:
        q = q.where(LogEntryRecord.service == service)
    result = await session.execute(q)
    return list(result.scalars().all())
