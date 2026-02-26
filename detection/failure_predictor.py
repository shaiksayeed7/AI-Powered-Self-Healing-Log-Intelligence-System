"""
Failure Predictor – predicts imminent service crashes from error-rate trends.

Algorithm
---------
* Maintains a short rolling window of per-minute error counts.
* Calculates the **error velocity** (percentage growth between oldest and
  newest bucket).
* If velocity exceeds ``CRASH_VELOCITY_THRESHOLD``, a crash prediction is
  issued with an estimated time-to-failure and confidence score.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Optional

import config
from ingestion.log_parser import LogEntry


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class PredictionResult:
    service: str
    predicted_crash: bool
    confidence: float           # 0–1
    estimated_minutes: Optional[int]
    cause: str
    error_velocity_pct: float   # percentage change in error rate

    def to_dict(self) -> dict:
        return {
            "service": self.service,
            "predicted_crash": self.predicted_crash,
            "confidence": round(self.confidence, 2),
            "estimated_minutes": self.estimated_minutes,
            "cause": self.cause,
            "error_velocity_pct": round(self.error_velocity_pct, 1),
        }


# ---------------------------------------------------------------------------
# Per-service bucket tracker
# ---------------------------------------------------------------------------

class _ServiceTracker:
    """Tracks error counts in 1-minute buckets for a single service."""

    BUCKET_SECONDS = 60

    def __init__(self, window: int) -> None:
        self._window = window
        # Each element: (bucket_start_ts, error_count)
        self._buckets: deque[tuple[float, int]] = deque(maxlen=window)
        self._current_bucket_start: float = time.time()
        self._current_count: int = 0

    def record(self, is_error: bool, now: float) -> None:
        if now - self._current_bucket_start >= self.BUCKET_SECONDS:
            self._buckets.append((self._current_bucket_start, self._current_count))
            self._current_bucket_start = now
            self._current_count = 0
        if is_error:
            self._current_count += 1

    def velocity_pct(self) -> float:
        """Return percentage change from oldest to newest complete bucket."""
        if len(self._buckets) < 2:
            return 0.0
        oldest = self._buckets[0][1]
        newest = self._buckets[-1][1]
        if oldest == 0:
            return 100.0 if newest > 0 else 0.0
        return ((newest - oldest) / oldest) * 100.0

    def recent_error_rate(self) -> float:
        """Errors per minute averaged over the window."""
        if not self._buckets:
            return float(self._current_count)
        counts = [b[1] for b in self._buckets]
        return sum(counts) / len(counts)


# ---------------------------------------------------------------------------
# Failure Predictor
# ---------------------------------------------------------------------------

class FailurePredictor:
    """
    Monitors per-service error trends and emits crash predictions.

    Call :meth:`process` for every incoming log entry.  When a crash is
    predicted for a service the method returns a
    :class:`PredictionResult` with ``predicted_crash=True``.
    """

    def __init__(
        self,
        prediction_window: int = config.PREDICTION_WINDOW,
        velocity_threshold: float = config.CRASH_VELOCITY_THRESHOLD,
        horizon_minutes: int = config.PREDICTION_HORIZON_MINUTES,
    ) -> None:
        self._prediction_window = prediction_window
        self._velocity_threshold = velocity_threshold
        self._horizon_minutes = horizon_minutes
        self._trackers: dict[str, _ServiceTracker] = {}

    def _get_tracker(self, service: str) -> _ServiceTracker:
        if service not in self._trackers:
            self._trackers[service] = _ServiceTracker(self._prediction_window)
        return self._trackers[service]

    def process(self, entry: LogEntry) -> PredictionResult:
        """Analyse a log entry and return a prediction for its service."""
        now = time.time()
        tracker = self._get_tracker(entry.service)
        is_error = entry.level in ("ERROR", "CRITICAL")
        tracker.record(is_error, now)

        velocity = tracker.velocity_pct()
        predicted_crash = velocity >= self._velocity_threshold

        # Confidence: scale 50–95 % based on how far above threshold
        if predicted_crash and self._velocity_threshold > 0:
            excess_ratio = min(velocity / self._velocity_threshold, 3.0)
            confidence = 0.50 + (excess_ratio - 1.0) * 0.225
            confidence = max(0.50, min(0.95, confidence))
        else:
            confidence = 0.0

        cause = (
            f"Error rate increased by {velocity:.1f}% – memory/resource saturation likely"
            if predicted_crash
            else "No significant error-rate trend detected"
        )

        return PredictionResult(
            service=entry.service,
            predicted_crash=predicted_crash,
            confidence=confidence,
            estimated_minutes=self._horizon_minutes if predicted_crash else None,
            cause=cause,
            error_velocity_pct=velocity,
        )

    def get_all_predictions(self) -> list[PredictionResult]:
        """Return current predictions for all tracked services."""
        results = []
        for service, tracker in self._trackers.items():
            velocity = tracker.velocity_pct()
            predicted = velocity >= self._velocity_threshold
            if predicted:
                excess_ratio = min(velocity / max(self._velocity_threshold, 1), 3.0)
                confidence = max(0.50, min(0.95, 0.50 + (excess_ratio - 1.0) * 0.225))
            else:
                confidence = 0.0
            results.append(
                PredictionResult(
                    service=service,
                    predicted_crash=predicted,
                    confidence=confidence,
                    estimated_minutes=self._horizon_minutes if predicted else None,
                    cause=(
                        f"Error rate velocity: {velocity:.1f}%"
                        if predicted
                        else "Normal"
                    ),
                    error_velocity_pct=velocity,
                )
            )
        return results
