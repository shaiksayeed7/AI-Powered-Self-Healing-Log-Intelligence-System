"""Tests for the log parsing engine."""

import pytest

from sentinelai.log_ingestion.parser import parse_log_line


class TestParseLogLine:
    def test_full_structured_line(self):
        line = "2026-02-27T01:23:10 ERROR payment-api DB_CONNECTION_TIMEOUT latency=320ms"
        record = parse_log_line(line)
        assert record is not None
        assert record["level"] == "ERROR"
        assert record["service"] == "payment-api"
        assert record["error_code"] == "DB_CONNECTION_TIMEOUT"
        assert record["latency_ms"] == 320.0
        assert "2026-02-27" in record["timestamp"]

    def test_python_logging_format(self):
        line = "2026-02-27 01:23:10,123 - payment-api - ERROR - Connection refused"
        record = parse_log_line(line)
        assert record is not None
        assert record["level"] == "ERROR"
        assert record["service"] == "payment-api"
        assert "Connection refused" in record["message"]

    def test_info_level(self):
        line = "2026-02-27T01:20:00 INFO payment-api SERVICE_STARTED latency=5ms"
        record = parse_log_line(line)
        assert record is not None
        assert record["level"] == "INFO"
        assert record["latency_ms"] == 5.0

    def test_warn_level(self):
        line = "2026-02-27T01:21:00 WARN payment-api SLOW_QUERY latency=450ms"
        record = parse_log_line(line)
        assert record is not None
        assert record["level"] == "WARN"

    def test_empty_line_returns_none(self):
        assert parse_log_line("") is None
        assert parse_log_line("   ") is None

    def test_unparseable_returns_none(self):
        assert parse_log_line("this is not a log line") is None

    def test_fallback_extracts_level(self):
        line = "some prefix 2026-02-27T01:23:10 then ERROR and more text"
        record = parse_log_line(line)
        assert record is not None
        assert record["level"] == "ERROR"

    def test_latency_inline_enrichment(self):
        line = "2026-02-27T01:23:10 ERROR svc-a MESSAGE latency=99ms extra"
        record = parse_log_line(line)
        assert record is not None
        assert record["latency_ms"] == 99.0

    def test_raw_preserved(self):
        line = "2026-02-27T01:23:10 ERROR payment-api DB_TIMEOUT"
        record = parse_log_line(line)
        assert record is not None
        assert record["raw"] == line

    def test_critical_level(self):
        line = "2026-02-27T01:22:10 CRITICAL payment-api SERVICE_DEGRADED Circuit breaker open"
        record = parse_log_line(line)
        assert record is not None
        assert record["level"] == "CRITICAL"
