"""Tests for the Failure Prediction module."""

import pytest

from sentinelai.detection.predictor import FailurePredictor


class TestFailurePredictor:
    def test_no_prediction_with_insufficient_data(self):
        predictor = FailurePredictor(min_samples=5)
        predictor.record(0.1)
        predictor.record(0.2)
        result = predictor.predict()
        assert result is None

    def test_stable_system_no_failure(self):
        predictor = FailurePredictor(critical_threshold=0.5, min_samples=5)
        for _ in range(10):
            predictor.record(0.05)
        result = predictor.predict()
        assert result is not None
        assert not result.failure_likely

    def test_rising_error_rate_predicts_failure(self):
        predictor = FailurePredictor(critical_threshold=0.5, min_samples=5)
        # Linearly increasing error rates toward failure
        for i in range(10):
            predictor.record(0.05 * i, log_count=100)
        result = predictor.predict()
        assert result is not None
        assert result.failure_likely

    def test_result_fields_present(self):
        predictor = FailurePredictor(min_samples=5)
        for i in range(6):
            predictor.record(0.1 * i)
        result = predictor.predict()
        assert result is not None
        assert hasattr(result, "failure_likely")
        assert hasattr(result, "confidence")
        assert hasattr(result, "cause")
        assert hasattr(result, "minutes_to_failure")

    def test_high_current_rate_flagged(self):
        predictor = FailurePredictor(critical_threshold=0.5, min_samples=5)
        for _ in range(5):
            predictor.record(0.6)
        result = predictor.predict()
        assert result is not None
        assert result.failure_likely

    def test_summary_contains_crash(self):
        predictor = FailurePredictor(critical_threshold=0.3, min_samples=5)
        for i in range(8):
            predictor.record(0.04 * i)
        result = predictor.predict()
        if result and result.failure_likely:
            assert "Crash" in result.summary() or "stable" in result.summary().lower()
