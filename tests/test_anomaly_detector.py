"""Tests for the Anomaly Detection Engine."""

import pytest

from sentinelai.detection.anomaly_detector import AnomalyDetector


def _make_record(level: str, service: str, minute: str, latency: float = 50.0) -> dict:
    return {
        "timestamp": f"2026-02-27T{minute}:00",
        "level": level,
        "service": service,
        "latency_ms": latency,
    }


class TestAnomalyDetector:
    def test_no_result_with_insufficient_data(self):
        detector = AnomalyDetector()
        detector.ingest(_make_record("ERROR", "svc", "01:00"))
        result = detector.check("svc")
        assert result is None

    def test_normal_error_rate_no_anomaly(self):
        detector = AnomalyDetector(z_threshold=2.5)
        # Feed 5 minutes of low error rate
        for i in range(5):
            detector.ingest(_make_record("INFO", "svc", f"01:0{i}"))
            detector.ingest(_make_record("INFO", "svc", f"01:0{i}"))
        # Add a new minute
        detector.ingest(_make_record("INFO", "svc", "01:06"))
        result = detector.check("svc")
        if result:
            assert not result.is_anomaly

    def test_anomaly_result_has_expected_fields(self):
        detector = AnomalyDetector(z_threshold=1.0)
        # Push several minutes of near-zero errors
        for i in range(6):
            for _ in range(10):
                detector.ingest(_make_record("INFO", "svc", f"01:0{i}"))
        # Spike: all errors in a new minute
        for _ in range(10):
            detector.ingest(_make_record("ERROR", "svc", "01:07"))
        result = detector.check("svc")
        assert result is not None
        assert hasattr(result, "is_anomaly")
        assert hasattr(result, "score")
        assert hasattr(result, "method")
        assert hasattr(result, "description")

    def test_error_spike_detected(self):
        detector = AnomalyDetector(z_threshold=1.0)
        # Baseline: 10 minutes of INFO only
        for i in range(10):
            for _ in range(20):
                detector.ingest(_make_record("INFO", "svc", f"01:{i:02d}"))
        # Spike: all ERROR in minute 11
        for _ in range(20):
            detector.ingest(_make_record("ERROR", "svc", "01:11"))
        result = detector.check("svc")
        assert result is not None
        assert result.is_anomaly

    def test_stop_sends_stop_signal(self):
        from sentinelai.log_ingestion.streamer import LogStreamer
        import tempfile, os
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.write("2026-02-27T01:00:00 INFO svc MSG\n")
            name = f.name
        streamer = LogStreamer(name)
        streamer.stop()
        assert not streamer._running
        os.unlink(name)
