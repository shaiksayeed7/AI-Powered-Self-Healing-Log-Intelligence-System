"""SQLite storage layer for SentinelAI.

Tables
------
* ``log_records``   – parsed log entries
* ``anomalies``     – detected anomaly events
* ``predictions``   – failure predictions
* ``rca_results``   – root cause analysis results
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List, Optional

from sentinelai.config import DATABASE_URL


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DATABASE_URL, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_url: str = DATABASE_URL) -> None:
    """Create tables if they do not exist."""
    conn = sqlite3.connect(db_url, check_same_thread=False)
    cur = conn.cursor()
    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS log_records (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   TEXT,
            level       TEXT,
            service     TEXT,
            error_code  TEXT,
            latency_ms  REAL,
            message     TEXT,
            raw         TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS anomalies (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            service     TEXT,
            is_anomaly  INTEGER,
            score       REAL,
            method      TEXT,
            description TEXT,
            detected_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS predictions (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            service             TEXT,
            failure_likely      INTEGER,
            minutes_to_failure  REAL,
            confidence          REAL,
            cause               TEXT,
            predicted_at        TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS rca_results (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            service          TEXT,
            probable_cause   TEXT,
            category         TEXT,
            matched_patterns TEXT,
            confidence       TEXT,
            analysed_at      TEXT DEFAULT (datetime('now'))
        );
        """
    )
    conn.commit()
    conn.close()


class Database:
    """Thin wrapper around the SQLite connection."""

    def __init__(self, db_url: str = DATABASE_URL) -> None:
        init_db(db_url)
        self._conn = sqlite3.connect(db_url, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

    # ── Log records ──────────────────────────────────────────────────────────

    def insert_log(self, record: Dict[str, Any]) -> None:
        self._conn.execute(
            """
            INSERT INTO log_records (timestamp, level, service, error_code,
                                     latency_ms, message, raw)
            VALUES (:timestamp, :level, :service, :error_code,
                    :latency_ms, :message, :raw)
            """,
            {
                "timestamp": record.get("timestamp"),
                "level": record.get("level"),
                "service": record.get("service"),
                "error_code": record.get("error_code"),
                "latency_ms": record.get("latency_ms"),
                "message": record.get("message", ""),
                "raw": record.get("raw", ""),
            },
        )
        self._conn.commit()

    def get_logs(
        self,
        service: Optional[str] = None,
        level: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict]:
        query = "SELECT * FROM log_records WHERE 1=1"
        params: list = []
        if service:
            query += " AND service = ?"
            params.append(service)
        if level:
            query += " AND level = ?"
            params.append(level.upper())
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    # ── Anomalies ─────────────────────────────────────────────────────────────

    def insert_anomaly(self, service: str, result: Any) -> None:
        self._conn.execute(
            """
            INSERT INTO anomalies (service, is_anomaly, score, method, description)
            VALUES (?, ?, ?, ?, ?)
            """,
            (service, int(result.is_anomaly), result.score, result.method, result.description),
        )
        self._conn.commit()

    def get_anomalies(self, limit: int = 50) -> List[Dict]:
        rows = self._conn.execute(
            "SELECT * FROM anomalies ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Predictions ───────────────────────────────────────────────────────────

    def insert_prediction(self, service: str, result: Any) -> None:
        self._conn.execute(
            """
            INSERT INTO predictions
                (service, failure_likely, minutes_to_failure, confidence, cause)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                service,
                int(result.failure_likely),
                result.minutes_to_failure,
                result.confidence,
                result.cause,
            ),
        )
        self._conn.commit()

    def get_predictions(self, limit: int = 50) -> List[Dict]:
        rows = self._conn.execute(
            "SELECT * FROM predictions ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ── RCA results ───────────────────────────────────────────────────────────

    def insert_rca(self, service: str, result: Any) -> None:
        self._conn.execute(
            """
            INSERT INTO rca_results
                (service, probable_cause, category, matched_patterns, confidence)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                service,
                result.probable_cause,
                result.category,
                json.dumps(result.matched_patterns),
                result.confidence,
            ),
        )
        self._conn.commit()

    def get_rca_results(self, limit: int = 50) -> List[Dict]:
        rows = self._conn.execute(
            "SELECT * FROM rca_results ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def close(self) -> None:
        self._conn.close()
