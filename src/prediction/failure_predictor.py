"""Time-series based failure predictor using error velocity."""
from collections import defaultdict, deque
from datetime import datetime
from typing import Dict, List, Optional


_ERROR_LEVELS = {"ERROR", "CRITICAL"}


class FailurePredictor:
    """Predicts impending failures by tracking error velocity per service."""

    # Keep up to 60 1-minute buckets (~1 hour of history)
    _BUCKET_SECONDS = 60
    _MAX_BUCKETS = 60

    def __init__(self):
        # service -> deque of (bucket_minute, error_count, total_count)
        self._buckets: Dict[str, deque] = defaultdict(lambda: deque(maxlen=self._MAX_BUCKETS))
        self._last_ts: Dict[str, Optional[str]] = defaultdict(lambda: None)

    # ------------------------------------------------------------------
    def update(self, log_entry: dict) -> None:
        service = log_entry.get("service", "unknown")
        ts_str = log_entry.get("timestamp", "")
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except Exception:
            ts = datetime.utcnow()

        bucket = int(ts.timestamp() // self._BUCKET_SECONDS)
        is_error = 1 if log_entry.get("level") in _ERROR_LEVELS else 0

        q = self._buckets[service]
        if q and q[-1][0] == bucket:
            prev = q[-1]
            q[-1] = (bucket, prev[1] + is_error, prev[2] + 1)
        else:
            q.append((bucket, is_error, 1))

        self._last_ts[service] = ts_str

    def predict_failure(self, service: Optional[str] = None) -> dict:
        """Return a prediction result for the given service (or worst-case if None)."""
        if service:
            return self._predict_for_service(service)

        # Find service with highest risk
        worst = {"predicted": False, "service": "none", "time_to_failure_minutes": None,
                 "confidence": 0.0, "cause": "No anomalies detected", "indicators": []}
        for svc in self._buckets:
            result = self._predict_for_service(svc)
            if result["confidence"] > worst["confidence"]:
                worst = result
        return worst

    # ------------------------------------------------------------------
    def _predict_for_service(self, service: str) -> dict:
        q = list(self._buckets.get(service, []))
        if len(q) < 3:
            return {"predicted": False, "service": service,
                    "time_to_failure_minutes": None,
                    "confidence": 0.0, "cause": "Insufficient data",
                    "indicators": []}

        # Compute error rates per bucket
        error_rates = [b[1] / max(b[2], 1) for b in q]
        recent = error_rates[-5:] if len(error_rates) >= 5 else error_rates

        # Simple linear trend on recent buckets
        n = len(recent)
        if n < 2:
            return {"predicted": False, "service": service,
                    "time_to_failure_minutes": None,
                    "confidence": 0.0, "cause": "Insufficient data",
                    "indicators": []}

        xs = list(range(n))
        x_mean = sum(xs) / n
        y_mean = sum(recent) / n
        num = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, recent))
        den = sum((x - x_mean) ** 2 for x in xs)
        slope = num / den if den != 0 else 0.0

        current_rate = recent[-1]
        total_errors = sum(b[1] for b in q[-5:])
        indicators = self._collect_indicators(service, current_rate, slope, total_errors)

        if slope <= 0 and current_rate < 0.3:
            return {"predicted": False, "service": service,
                    "time_to_failure_minutes": None,
                    "confidence": 0.0, "cause": "Error rate stable or declining",
                    "indicators": indicators}

        # Estimate time-to-failure: how many buckets until error rate hits 0.9
        if slope > 0 and current_rate < 0.9:
            ttf_buckets = (0.9 - current_rate) / slope
            ttf_minutes = max(1, round(ttf_buckets * self._BUCKET_SECONDS / 60))
        else:
            ttf_minutes = 1 if current_rate >= 0.9 else None

        confidence = min(0.95, current_rate * 0.5 + max(0.0, slope) * 2.0 + (0.3 if total_errors > 10 else 0))

        cause = self._infer_cause(indicators)

        return {
            "predicted": confidence > 0.3 or current_rate >= 0.5,
            "service": service,
            "time_to_failure_minutes": ttf_minutes,
            "confidence": round(confidence, 2),
            "cause": cause,
            "indicators": indicators,
        }

    @staticmethod
    def _collect_indicators(service: str, rate: float, slope: float, total_errors: int) -> List[str]:
        ind = []
        if rate > 0.5:
            ind.append(f"High error rate ({rate:.0%}) for {service}")
        if slope > 0.05:
            ind.append(f"Rising error velocity (+{slope:.2f}/min)")
        if total_errors > 10:
            ind.append(f"{total_errors} errors in last 5 minutes")
        return ind

    @staticmethod
    def _infer_cause(indicators: List[str]) -> str:
        text = " ".join(indicators).lower()
        if "db" in text or "connection" in text or "timeout" in text:
            return "DB connection saturation"
        if "memory" in text or "oom" in text:
            return "Memory saturation trend"
        if "auth" in text:
            return "Auth service degradation"
        if indicators:
            return "Rising error velocity"
        return "No anomalies detected"
