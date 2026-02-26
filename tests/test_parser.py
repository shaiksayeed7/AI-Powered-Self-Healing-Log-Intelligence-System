"""Tests for LogParser."""
import pytest
from src.parser.log_parser import LogParser


@pytest.fixture
def parser():
    return LogParser()


def test_iso_format_error_with_latency(parser):
    line = "2026-02-27T01:23:10 ERROR payment-api DB_CONNECTION_TIMEOUT latency=2500ms"
    result = parser.parse(line)
    assert result is not None
    assert result["level"] == "ERROR"
    assert result["service"] == "payment-api"
    assert result["latency_ms"] == 2500
    assert result["error_type"] is not None
    assert "2026-02-27" in result["timestamp"]


def test_bracket_format_warn_with_latency(parser):
    line = '[2026-02-27 01:23:10] WARN auth-service "Connection refused" latency=150ms'
    result = parser.parse(line)
    assert result is not None
    assert result["level"] == "WARN"
    assert result["service"] == "auth-service"
    assert result["latency_ms"] == 150
    assert "Connection refused" in result["message"]


def test_iso_millis_format_info(parser):
    line = "2026-02-27T01:23:10.123Z INFO user-service Request processed latency=45ms"
    result = parser.parse(line)
    assert result is not None
    assert result["level"] == "INFO"
    assert result["service"] == "user-service"
    assert result["latency_ms"] == 45
    assert result["error_type"] is None


def test_critical_level(parser):
    line = "2026-02-27T01:22:35 CRITICAL payment-api Service degraded DB unavailable latency=5000ms"
    result = parser.parse(line)
    assert result is not None
    assert result["level"] == "CRITICAL"
    assert result["service"] == "payment-api"
    assert result["latency_ms"] == 5000


def test_no_latency(parser):
    line = "2026-02-27T01:20:00 INFO payment-api Service started successfully"
    result = parser.parse(line)
    assert result is not None
    assert result["latency_ms"] is None
    assert result["level"] == "INFO"


def test_unparseable_line_returns_none(parser):
    assert parser.parse("this is not a log line") is None
    assert parser.parse("") is None
    assert parser.parse("   ") is None


def test_warning_normalised(parser):
    line = "2026-02-27T01:00:00 WARNING some-service Some message latency=10ms"
    result = parser.parse(line)
    assert result is not None
    assert result["level"] == "WARN"


def test_bracket_format_error(parser):
    line = '[2026-02-27 01:22:20] ERROR db-service "CONNECTION_REFUSED" latency=5000ms'
    result = parser.parse(line)
    assert result is not None
    assert result["level"] == "ERROR"
    assert result["service"] == "db-service"
    assert result["error_type"] is not None


def test_timestamp_field_present(parser):
    line = "2026-02-27T01:20:05 INFO auth-service Token validated latency=12ms"
    result = parser.parse(line)
    assert result is not None
    assert "timestamp" in result
    assert result["timestamp"].startswith("2026-02-27")


def test_raw_field_preserved(parser):
    line = "2026-02-27T01:20:05 INFO auth-service Token validated latency=12ms"
    result = parser.parse(line)
    assert result is not None
    assert result["raw"] == line
