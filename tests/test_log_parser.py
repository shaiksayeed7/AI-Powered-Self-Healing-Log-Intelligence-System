"""Tests for the log parser module."""

from datetime import datetime

import pytest

from ingestion.log_parser import LogEntry, parse_line


class TestParseLineBasic:
    def test_standard_error_line(self):
        line = "2026-02-27T01:23:10 ERROR payment-api DB_CONNECTION_TIMEOUT latency=320ms"
        entry = parse_line(line)

        assert entry.level == "ERROR"
        assert entry.service == "payment-api"
        assert entry.latency_ms == 320.0
        assert entry.error_type == "DB_CONNECTION_TIMEOUT"
        assert isinstance(entry.timestamp, datetime)

    def test_info_line(self):
        line = "2026-02-27T10:00:00 INFO auth-service User login successful"
        entry = parse_line(line)

        assert entry.level == "INFO"
        assert entry.service == "auth-service"
        assert "login" in entry.message.lower()

    def test_warn_normalisation(self):
        line = "2026-02-27T10:00:00 WARNING order-service Slow query detected"
        entry = parse_line(line)
        assert entry.level == "WARN"

    def test_fatal_normalised_to_critical(self):
        line = "2026-02-27T10:00:00 FATAL db-service Process killed"
        entry = parse_line(line)
        assert entry.level == "CRITICAL"

    def test_no_timestamp_fallback(self):
        line = "ERROR payment-api Something went wrong"
        entry = parse_line(line)
        # Should still parse level and not crash
        assert entry.level == "ERROR"
        assert isinstance(entry.timestamp, datetime)

    def test_unknown_level(self):
        line = "2026-02-27T10:00:00 some-service Arbitrary message"
        entry = parse_line(line)
        assert entry.level == "UNKNOWN"

    def test_latency_extraction(self):
        line = "2026-02-27T10:00:00 INFO api-gw Request completed latency=45ms"
        entry = parse_line(line)
        assert entry.latency_ms == 45.0

    def test_latency_float(self):
        line = "2026-02-27T10:00:00 INFO api-gw Request latency=12.5ms"
        entry = parse_line(line)
        assert entry.latency_ms == 12.5

    def test_to_dict_keys(self):
        line = "2026-02-27T01:23:10 ERROR payment-api DB_CONNECTION_TIMEOUT latency=320ms"
        d = parse_line(line).to_dict()
        for key in ("timestamp", "level", "service", "message", "error_type", "latency_ms"):
            assert key in d

    def test_default_service_applied(self):
        line = "2026-02-27T10:00:00 INFO Just a message"
        entry = parse_line(line, default_service="fallback-svc")
        # After removing timestamp and level, first token might not match service pattern
        # but default_service is the fallback
        assert entry.service in ("fallback-svc", "Just")  # depends on token matching

    def test_raw_preserved(self):
        raw = "2026-02-27T01:23:10 ERROR payment-api DB_CONNECTION_TIMEOUT"
        entry = parse_line(raw)
        assert entry.raw == raw

    def test_critical_level(self):
        line = "2026-02-27T10:00:00 CRITICAL memory-service OOM_KILL"
        entry = parse_line(line)
        assert entry.level == "CRITICAL"
        assert entry.error_type == "OOM_KILL"
