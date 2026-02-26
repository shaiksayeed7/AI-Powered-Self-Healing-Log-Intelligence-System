"""Tests for the anomaly detector module."""

import time

import pytest

from detection.anomaly_detector import AnomalyDetector, AnomalyResult
from ingestion.log_parser import LogEntry


def _make_entry(level="INFO", latency_ms=None, service="test-svc"):
    from datetime import datetime
    return LogEntry(
        raw="",
        timestamp=datetime.utcnow(),
        level=level,
        service=service,
        message="test message",
        latency_ms=latency_ms,
    )


class TestAnomalyDetector:
    def setup_method(self):
        self.detector = AnomalyDetector(
            window_size=50,
            zscore_threshold=3.0,
            contamination=0.05,
        )

    def test_returns_anomaly_result(self):
        entry = _make_entry()
        result = self.detector.process(entry)
        assert isinstance(result, AnomalyResult)
        assert hasattr(result, "is_anomaly")
        assert hasattr(result, "zscore")
        assert hasattr(result, "isolation_score")
        assert hasattr(result, "reason")

    def test_normal_entries_not_flagged_initially(self):
        # First two entries have no window yet → z-score is None → not anomaly
        entry = _make_entry("INFO", latency_ms=10)
        result = self.detector.process(entry)
        assert result.zscore is None

    def test_spike_detected_by_zscore(self):
        # Feed many normal entries then one huge spike
        for _ in range(60):
            self.detector.process(_make_entry("INFO", latency_ms=10))
        # Now feed a huge-latency entry
        spike = _make_entry("INFO", latency_ms=10000)
        result = self.detector.process(spike)
        assert result.zscore is not None
        assert result.zscore > 3.0
        assert result.is_anomaly

    def test_error_entries_tracked(self):
        entry = _make_entry("ERROR")
        result = self.detector.process(entry)
        assert isinstance(result, AnomalyResult)

    def test_to_dict(self):
        entry = _make_entry()
        result = self.detector.process(entry)
        d = result.to_dict()
        for key in ("is_anomaly", "zscore", "isolation_score", "reason"):
            assert key in d

    def test_multiple_services(self):
        e1 = _make_entry(service="svc-a")
        e2 = _make_entry(service="svc-b")
        r1 = self.detector.process(e1)
        r2 = self.detector.process(e2)
        # Both should return valid results
        assert isinstance(r1, AnomalyResult)
        assert isinstance(r2, AnomalyResult)
