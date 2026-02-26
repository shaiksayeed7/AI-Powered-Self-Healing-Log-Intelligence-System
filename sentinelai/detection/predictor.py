"""Failure Prediction Module.

Uses a simple linear-regression trend over a rolling error-rate time-series
to project when the error rate would exceed a critical threshold, which is
treated as a "predicted crash" event.

Output example
--------------
::

    ⚠️ Predicted Service Crash in ~12 minutes
    Confidence: 78%
    Cause: Error rate saturation trend
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

import numpy as np

from sentinelai.config import PREDICTION_MIN_SAMPLES, PREDICTION_LOOKAHEAD_MINUTES


@dataclass
class PredictionResult:
    """Result from the failure predictor."""

    failure_likely: bool
    minutes_to_failure: Optional[float]  # None if no failure predicted
    confidence: float  # 0.0 – 1.0
    cause: str
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def summary(self) -> str:
        if not self.failure_likely:
            return f"System appears stable (confidence {self.confidence:.0%})."
        mins = f"~{self.minutes_to_failure:.0f}" if self.minutes_to_failure else "unknown"
        return (
            f"⚠️ Predicted Service Crash in {mins} minutes\n"
            f"Confidence: {self.confidence:.0%}\n"
            f"Cause: {self.cause}"
        )


class FailurePredictor:
    """Track per-minute error rates and predict future failures.

    Parameters
    ----------
    critical_threshold:
        Error rate (0–1) above which we consider the service crashed.
    lookahead_minutes:
        How far into the future to project the trend.
    min_samples:
        Minimum number of data points before making a prediction.
    """

    def __init__(
        self,
        critical_threshold: float = 0.5,
        lookahead_minutes: int = PREDICTION_LOOKAHEAD_MINUTES,
        min_samples: int = PREDICTION_MIN_SAMPLES,
    ) -> None:
        self._threshold = critical_threshold
        self._lookahead = lookahead_minutes
        self._min_samples = min_samples
        self._error_rates: List[float] = []
        self._log_counts: List[int] = []

    def record(self, error_rate: float, log_count: int = 0) -> None:
        """Add a new data point (one per minute bucket)."""
        self._error_rates.append(error_rate)
        self._log_counts.append(log_count)

    def predict(self) -> Optional[PredictionResult]:
        """Return a :class:`PredictionResult` or *None* if not enough data."""
        n = len(self._error_rates)
        if n < self._min_samples:
            return None

        rates = np.array(self._error_rates[-self._lookahead * 2 :], dtype=float)
        x = np.arange(len(rates), dtype=float)

        # Linear regression: y = slope * x + intercept
        slope, intercept = np.polyfit(x, rates, 1)

        current_rate = rates[-1]
        trend_direction = "rising" if slope > 0 else "stable/falling"

        # Estimate minutes until threshold is crossed
        minutes_to_failure: Optional[float] = None
        if slope > 1e-6:
            # threshold = slope * t + intercept  =>  t = (threshold - intercept) / slope
            t = (self._threshold - intercept) / slope
            remaining = t - (len(rates) - 1)
            if 0 < remaining <= self._lookahead:
                minutes_to_failure = remaining

        failure_likely = (
            minutes_to_failure is not None
            or current_rate >= self._threshold * 0.8
        )

        # Confidence: based on R² of the fit
        predicted = slope * x + intercept
        ss_res = float(np.sum((rates - predicted) ** 2))
        ss_tot = float(np.sum((rates - rates.mean()) ** 2))
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
        confidence = max(0.0, min(1.0, abs(r2)))

        cause = _determine_cause(slope, current_rate, self._log_counts)

        return PredictionResult(
            failure_likely=failure_likely,
            minutes_to_failure=minutes_to_failure,
            confidence=confidence,
            cause=cause,
        )


def _determine_cause(slope: float, current_rate: float, log_counts: List[int]) -> str:
    """Heuristic cause label based on trends."""
    if current_rate >= 0.5:
        return "High sustained error rate"
    if slope > 0.05:
        return "Rapidly increasing error rate"
    if log_counts and len(log_counts) > 1:
        recent = log_counts[-3:]
        if all(recent[i] > recent[i - 1] for i in range(1, len(recent))):
            return "Log volume surge (possible memory/CPU saturation)"
    return "Error rate saturation trend"
