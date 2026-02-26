"""Tests for AnomalyDetector."""
import pytest
from src.anomaly_detection.detector import AnomalyDetector


def _make_entry(level="INFO", service="svc-a", latency=50):
    return {"timestamp": "2026-02-27T01:00:00", "level": level,
            "service": service, "message": "msg", "latency_ms": latency,
            "error_type": None if level == "INFO" else "ERR", "raw": ""}


def _make_entries(n, level="INFO", service="svc-a", latency=50):
    return [_make_entry(level=level, service=service, latency=latency) for _ in range(n)]


def test_no_anomaly_on_normal_logs():
    detector = AnomalyDetector(window_size=50, z_threshold=2.5)
    entries = _make_entries(40, level="INFO", latency=50)
    anomalies = detector.detect_anomalies(entries)
    # Normal uniform logs should not trigger error spike
    error_spikes = [a for a in anomalies if a["type"] == "ERROR_SPIKE"]
    assert len(error_spikes) == 0


def test_error_spike_detected():
    detector = AnomalyDetector(window_size=100, z_threshold=2.5)
    # Fill window with mostly OK logs
    normal = _make_entries(80, level="INFO", latency=50)
    for e in normal:
        detector.add_log_entry(e)
    # Now inject many errors
    error_entries = _make_entries(20, level="ERROR", service="payment-api", latency=3000)
    anomalies = detector.detect_anomalies(error_entries)
    types = [a["type"] for a in anomalies]
    assert "ERROR_SPIKE" in types or "UNUSUAL_FREQUENCY" in types


def test_latency_jump_detected():
    detector = AnomalyDetector(window_size=100, z_threshold=2.5)
    normal = _make_entries(80, level="INFO", latency=50)
    for e in normal:
        detector.add_log_entry(e)
    high_latency = _make_entries(20, level="WARN", latency=5000)
    anomalies = detector.detect_anomalies(high_latency)
    types = [a["type"] for a in anomalies]
    assert "LATENCY_JUMP" in types


def test_get_error_rate():
    detector = AnomalyDetector(window_size=10, z_threshold=2.5)
    for e in _make_entries(5, level="INFO"):
        detector.add_log_entry(e)
    for e in _make_entries(5, level="ERROR"):
        detector.add_log_entry(e)
    rate = detector.get_error_rate()
    assert 0.4 <= rate <= 0.6


def test_get_latency_stats():
    detector = AnomalyDetector(window_size=20)
    for e in _make_entries(20, latency=100):
        detector.add_log_entry(e)
    stats = detector.get_latency_stats()
    assert "mean" in stats
    assert abs(stats["mean"] - 100) < 1


def test_multiple_services_no_false_positive():
    detector = AnomalyDetector(window_size=100, z_threshold=2.5)
    entries = []
    for svc in ["svc-a", "svc-b", "svc-c"]:
        entries.extend(_make_entries(25, level="INFO", service=svc, latency=60))
    anomalies = detector.detect_anomalies(entries)
    error_spikes = [a for a in anomalies if a["type"] == "ERROR_SPIKE"]
    assert len(error_spikes) == 0


def test_anomaly_has_required_fields():
    detector = AnomalyDetector(window_size=100, z_threshold=2.5)
    normal = _make_entries(80, level="INFO", latency=50)
    for e in normal:
        detector.add_log_entry(e)
    errors = _make_entries(20, level="ERROR", service="bad-svc", latency=5000)
    anomalies = detector.detect_anomalies(errors)
    for a in anomalies:
        assert "type" in a
        assert "severity" in a
        assert "service" in a
        assert "description" in a
        assert "timestamp" in a
        assert "metrics" in a
