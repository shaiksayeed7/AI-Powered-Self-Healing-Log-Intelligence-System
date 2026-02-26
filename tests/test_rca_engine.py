"""Tests for the Root Cause Analysis engine."""

from datetime import datetime

import pytest

from analysis.rca_engine import RCAEngine, RCAResult
from ingestion.log_parser import LogEntry


def _entry(level="INFO", message="ok", service="svc", latency_ms=None):
    return LogEntry(
        raw="",
        timestamp=datetime.utcnow(),
        level=level,
        service=service,
        message=message,
        latency_ms=latency_ms,
    )


def _make_entries_with_db_overload():
    entries = []
    # High error rate
    for _ in range(7):
        entries.append(_entry("ERROR", "DB connection timeout"))
    for _ in range(3):
        entries.append(_entry("INFO", "ok"))
    # DB timeout message
    entries.append(_entry("ERROR", "DB_CONNECTION_TIMEOUT occurred"))
    # Connection pool exhaustion
    entries.append(_entry("ERROR", "connection pool exhausted max_connections reached"))
    return entries


class TestRCAEngine:
    def setup_method(self):
        self.engine = RCAEngine()

    def test_returns_rca_result(self):
        result = self.engine.analyse([_entry()])
        assert isinstance(result, RCAResult)

    def test_empty_entries(self):
        result = self.engine.analyse([])
        assert result.probable_cause is None
        assert result.confidence == 0.0

    def test_db_overload_detected(self):
        entries = _make_entries_with_db_overload()
        result = self.engine.analyse(entries)
        assert result.matched_rule == "DB_OVERLOAD"
        assert result.probable_cause is not None
        assert "database" in result.probable_cause.lower() or "db" in result.probable_cause.lower()
        assert result.confidence >= 0.80

    def test_disk_full_detected(self):
        entries = [_entry("ERROR", "no space left on device") for _ in range(5)]
        result = self.engine.analyse(entries)
        assert result.matched_rule == "DISK_FULL"
        assert result.confidence >= 0.90

    def test_memory_saturation_detected(self):
        entries = []
        for _ in range(7):
            entries.append(_entry("ERROR", "out of memory – process killed"))
        for _ in range(3):
            entries.append(_entry("INFO", "ok"))
        result = self.engine.analyse(entries)
        assert result.matched_rule == "MEMORY_SATURATION"

    def test_general_error_spike(self):
        entries = [_entry("ERROR", "Unknown error") for _ in range(8)]
        entries += [_entry("INFO", "ok") for _ in range(2)]
        result = self.engine.analyse(entries)
        # Should at least match GENERAL_ERROR_SPIKE
        assert result.matched_rule is not None

    def test_to_dict(self):
        result = self.engine.analyse([_entry()])
        d = result.to_dict()
        for key in ("probable_cause", "matched_rule", "signals", "confidence"):
            assert key in d

    def test_high_latency_db(self):
        entries = []
        for _ in range(5):
            entries.append(_entry("ERROR", "DB query timeout", latency_ms=1200))
        result = self.engine.analyse(entries)
        # Should match HIGH_LATENCY_DB or DB_OVERLOAD
        assert result.matched_rule is not None
