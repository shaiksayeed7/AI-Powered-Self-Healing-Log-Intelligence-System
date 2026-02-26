"""
Anomaly Detector – identifies unusual behaviour in a stream of log entries.

Two complementary strategies are combined:

1. **Z-score detector** – fast, stateless rolling-window check.  Flags a
   sample when its value is more than ``ZSCORE_THRESHOLD`` standard
   deviations away from the rolling mean.

2. **Isolation Forest detector** – trains an Isolation Forest on the last
   ``ANOMALY_WINDOW_SIZE`` feature vectors and scores every new sample.

Both detectors operate on a feature vector built from each
:class:`~ingestion.log_parser.LogEntry`:

* ``is_error``  – 1 if level is ERROR/CRITICAL, else 0
* ``latency_ms`` – latency in milliseconds (0 when absent)
* ``error_velocity`` – rolling rate of error lines per 60-s window
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Optional

import numpy as np
from sklearn.ensemble import IsolationForest

import config
from ingestion.log_parser import LogEntry


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class AnomalyResult:
    entry: LogEntry
    is_anomaly: bool
    zscore: Optional[float]
    isolation_score: Optional[float]
    reason: str

    def to_dict(self) -> dict:
        return {
            "timestamp": self.entry.timestamp.isoformat(),
            "service": self.entry.service,
            "level": self.entry.level,
            "message": self.entry.message,
            "is_anomaly": self.is_anomaly,
            "zscore": round(self.zscore, 3) if self.zscore is not None else None,
            "isolation_score": (
                round(self.isolation_score, 3)
                if self.isolation_score is not None
                else None
            ),
            "reason": self.reason,
        }


# ---------------------------------------------------------------------------
# Feature extraction
# ---------------------------------------------------------------------------

def _feature_vector(entry: LogEntry, error_velocity: float) -> np.ndarray:
    is_error = 1.0 if entry.level in ("ERROR", "CRITICAL") else 0.0
    latency = entry.latency_ms if entry.latency_ms is not None else 0.0
    return np.array([is_error, latency, error_velocity], dtype=float)


# ---------------------------------------------------------------------------
# Anomaly Detector
# ---------------------------------------------------------------------------

class AnomalyDetector:
    """
    Stateful anomaly detector.  Call :meth:`process` for each incoming
    :class:`~ingestion.log_parser.LogEntry`; it returns an
    :class:`AnomalyResult`.
    """

    def __init__(
        self,
        window_size: int = config.ANOMALY_WINDOW_SIZE,
        zscore_threshold: float = config.ZSCORE_THRESHOLD,
        contamination: float = config.ISOLATION_FOREST_CONTAMINATION,
    ) -> None:
        self._window_size = window_size
        self._zscore_threshold = zscore_threshold
        self._contamination = contamination

        # Rolling window of feature vectors
        self._window: deque[np.ndarray] = deque(maxlen=window_size)

        # Error-velocity tracking (timestamps of recent errors)
        self._error_timestamps: deque[float] = deque()

        # Isolation Forest – retrained periodically
        self._iforest: Optional[IsolationForest] = None
        self._samples_since_retrain: int = 0
        self._retrain_interval: int = max(10, window_size // 5)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _error_velocity(self, now: float, window_secs: float = 60.0) -> float:
        """Return the number of errors in the last *window_secs* seconds."""
        cutoff = now - window_secs
        while self._error_timestamps and self._error_timestamps[0] < cutoff:
            self._error_timestamps.popleft()
        return float(len(self._error_timestamps))

    def _zscore(self, vec: np.ndarray) -> Optional[float]:
        if len(self._window) < 2:
            return None
        data = np.array(self._window)
        means = data.mean(axis=0)
        stds = data.std(axis=0)
        diff = np.abs(vec - means)
        # When std == 0 but the value differs from mean, treat as a large deviation
        with np.errstate(divide="ignore", invalid="ignore"):
            zscores = np.where(
                stds > 0,
                diff / stds,
                np.where(diff > 0, self._zscore_threshold + 1.0, 0.0),
            )
        return float(np.max(zscores))

    def _retrain_iforest(self) -> None:
        if len(self._window) < max(10, self._retrain_interval):
            return
        data = np.array(self._window)
        self._iforest = IsolationForest(
            contamination=self._contamination,
            random_state=42,
            n_estimators=50,
        )
        self._iforest.fit(data)
        self._samples_since_retrain = 0

    def _isolation_score(self, vec: np.ndarray) -> Optional[float]:
        if self._iforest is None:
            return None
        score = self._iforest.decision_function(vec.reshape(1, -1))[0]
        return float(score)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process(self, entry: LogEntry) -> AnomalyResult:
        """Analyse a single log entry and return an :class:`AnomalyResult`."""
        now = time.time()

        if entry.level in ("ERROR", "CRITICAL"):
            self._error_timestamps.append(now)

        velocity = self._error_velocity(now)
        vec = _feature_vector(entry, velocity)

        zscore = self._zscore(vec)
        self._window.append(vec)

        # Periodic Isolation Forest retraining
        self._samples_since_retrain += 1
        if self._samples_since_retrain >= self._retrain_interval:
            self._retrain_iforest()

        iso_score = self._isolation_score(vec)

        # Decide
        reasons: list[str] = []
        is_anomaly = False

        if zscore is not None and zscore > self._zscore_threshold:
            is_anomaly = True
            reasons.append(f"Z-score {zscore:.2f} > threshold {self._zscore_threshold}")

        if iso_score is not None and iso_score < 0:
            is_anomaly = True
            reasons.append(f"Isolation Forest score {iso_score:.3f} (negative = outlier)")

        if not reasons:
            reasons.append("normal")

        return AnomalyResult(
            entry=entry,
            is_anomaly=is_anomaly,
            zscore=zscore,
            isolation_score=iso_score,
            reason="; ".join(reasons),
        )
