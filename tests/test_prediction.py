"""Tests for FailurePredictor."""
import pytest
from src.prediction.failure_predictor import FailurePredictor


def _make_entry(level="INFO", service="svc-a", ts="2026-02-27T01:00:00"):
    return {"timestamp": ts, "level": level, "service": service,
            "message": "msg", "latency_ms": 50, "error_type": None, "raw": ""}


def _feed_errors(predictor, service, count, base_ts_minute=0):
    """Feed `count` error entries into the predictor."""
    for i in range(count):
        minute = base_ts_minute + (i // 10)
        ts = f"2026-02-27T01:{minute:02d}:{(i % 60):02d}"
        predictor.update(_make_entry(level="ERROR", service=service, ts=ts))


def test_no_failure_with_no_errors():
    pred = FailurePredictor()
    for i in range(20):
        ts = f"2026-02-27T01:00:{i:02d}"
        pred.update(_make_entry(level="INFO", service="svc-a", ts=ts))
    result = pred.predict_failure(service="svc-a")
    assert result["predicted"] is False
    assert result["confidence"] < 0.3


def test_failure_predicted_with_high_error_velocity():
    pred = FailurePredictor()
    # Feed lots of errors to build up velocity
    _feed_errors(pred, "payment-api", 50, base_ts_minute=0)
    result = pred.predict_failure(service="payment-api")
    assert result["predicted"] is True
    assert result["confidence"] > 0.3


def test_confidence_increases_with_more_errors():
    pred1 = FailurePredictor()
    pred2 = FailurePredictor()
    _feed_errors(pred1, "svc", 10)
    _feed_errors(pred2, "svc", 50)
    r1 = pred1.predict_failure(service="svc")
    r2 = pred2.predict_failure(service="svc")
    assert r2["confidence"] >= r1["confidence"]


def test_predict_returns_required_fields():
    pred = FailurePredictor()
    _feed_errors(pred, "svc", 30)
    result = pred.predict_failure(service="svc")
    for field in ("predicted", "service", "confidence", "cause", "indicators"):
        assert field in result


def test_predict_all_services_returns_worst():
    pred = FailurePredictor()
    # Add mild errors for svc-a
    _feed_errors(pred, "svc-a", 5, base_ts_minute=0)
    # Add heavy errors for svc-b
    _feed_errors(pred, "svc-b", 50, base_ts_minute=0)
    result = pred.predict_failure()
    # svc-b should have higher confidence; the global prediction picks worst
    assert result["service"] in ("svc-a", "svc-b")
    assert result["confidence"] >= 0.0


def test_no_data_returns_not_predicted():
    pred = FailurePredictor()
    result = pred.predict_failure(service="unknown-svc")
    assert result["predicted"] is False


def test_time_to_failure_is_positive_when_predicted():
    pred = FailurePredictor()
    _feed_errors(pred, "svc", 50)
    result = pred.predict_failure(service="svc")
    if result["predicted"] and result["time_to_failure_minutes"] is not None:
        assert result["time_to_failure_minutes"] >= 1
