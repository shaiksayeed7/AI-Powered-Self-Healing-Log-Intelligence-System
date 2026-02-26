"""Anomaly Detection Engine.

Two complementary approaches are used:

1. **Z-score detector** – fast, stateless, detects sudden spikes in error rate
   using a rolling window of per-minute buckets.
2. **Isolation Forest** – unsupervised ML model that learns a multi-dimensional
   baseline (error rate + latency + log frequency) and flags outliers.

Both detectors operate on *feature vectors* derived from parsed log records.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Deque, List, Optional

import numpy as np

from sentinelai.config import (
    ANOMALY_WINDOW_SIZE,
    ANOMALY_Z_THRESHOLD,
    ISOLATION_FOREST_MIN_SAMPLES,
)


@dataclass
class AnomalyResult:
    """Result from the anomaly detector."""

    is_anomaly: bool
    score: float  # higher = more anomalous
    method: str  # "zscore" | "isolation_forest" | "combined"
    description: str
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class _Bucket:
    """One-minute statistics bucket."""

    minute: str  # "YYYY-MM-DDTHH:MM"
    error_count: int = 0
    total_count: int = 0
    total_latency_ms: float = 0.0
    latency_count: int = 0

    @property
    def error_rate(self) -> float:
        return self.error_count / self.total_count if self.total_count else 0.0

    @property
    def avg_latency(self) -> float:
        return (
            self.total_latency_ms / self.latency_count if self.latency_count else 0.0
        )


class AnomalyDetector:
    """Stateful anomaly detector.

    Call :meth:`ingest` for every parsed log record.  After each ingestion
    :meth:`check` evaluates the current minute bucket and returns an
    :class:`AnomalyResult` (or *None* if not enough data yet).
    """

    def __init__(
        self,
        window_size: int = ANOMALY_WINDOW_SIZE,
        z_threshold: float = ANOMALY_Z_THRESHOLD,
        if_min_samples: int = ISOLATION_FOREST_MIN_SAMPLES,
    ) -> None:
        self._window: Deque[_Bucket] = deque(maxlen=window_size)
        self._current: Optional[_Bucket] = None
        self._z_threshold = z_threshold
        self._if_min_samples = if_min_samples
        self._history: List[List[float]] = []  # for Isolation Forest training
        self._model = None  # lazy-loaded IsolationForest

    # ── Ingestion ─────────────────────────────────────────────────────────────

    def ingest(self, record: dict) -> None:
        """Feed a parsed log record into the detector."""
        ts_str: str = record.get("timestamp", "")
        minute = ts_str[:16] if len(ts_str) >= 16 else datetime.now(timezone.utc).isoformat()[:16]

        if self._current is None or self._current.minute != minute:
            if self._current is not None:
                self._commit_bucket()
            self._current = _Bucket(minute=minute)

        level = record.get("level", "INFO").upper()
        self._current.total_count += 1
        if level in ("ERROR", "CRITICAL", "FATAL"):
            self._current.error_count += 1

        latency = record.get("latency_ms")
        if latency is not None:
            self._current.total_latency_ms += float(latency)
            self._current.latency_count += 1

    def _commit_bucket(self) -> None:
        """Push the completed bucket onto the rolling window."""
        b = self._current
        self._window.append(b)
        self._history.append([b.error_rate, b.avg_latency, b.total_count])
        # Retrain Isolation Forest when enough samples are available
        if len(self._history) >= self._if_min_samples:
            self._train_isolation_forest()

    def _train_isolation_forest(self) -> None:
        from sklearn.ensemble import IsolationForest

        X = np.array(self._history)
        self._model = IsolationForest(contamination=0.1, random_state=42)
        self._model.fit(X)

    # ── Detection ─────────────────────────────────────────────────────────────

    def check(self, service: Optional[str] = None) -> Optional[AnomalyResult]:
        """Evaluate the current window for anomalies.

        Returns an :class:`AnomalyResult` or *None* if there is not enough
        data to make a decision.
        """
        if self._current is None or len(self._window) < 2:
            return None

        error_rates = [b.error_rate for b in self._window]
        latencies = [b.avg_latency for b in self._window]

        zscore_result = self._zscore_check(
            self._current.error_rate, error_rates, service
        )
        if_result = self._isolation_forest_check(
            self._current.error_rate,
            self._current.avg_latency,
            self._current.total_count,
            service,
        )

        # Combine: anomaly if either detector fires
        if zscore_result and zscore_result.is_anomaly:
            return zscore_result
        if if_result and if_result.is_anomaly:
            return if_result
        # Return a non-anomaly result so callers always get feedback once ready
        return AnomalyResult(
            is_anomaly=False,
            score=0.0,
            method="combined",
            description="No anomaly detected.",
        )

    def _zscore_check(
        self, current_rate: float, history: List[float], service: Optional[str]
    ) -> Optional[AnomalyResult]:
        if len(history) < 2:
            return None
        arr = np.array(history)
        mean, std = arr.mean(), arr.std()
        if std == 0:
            # If baseline is all zeros but current rate is non-zero, that's anomalous
            if current_rate > 0:
                desc = (
                    f"⚠️ Anomaly detected{' in ' + service if service else ''}: "
                    f"error rate jumped from 0% baseline to {current_rate:.1%}."
                )
                return AnomalyResult(is_anomaly=True, score=float(current_rate * 10),
                                     method="zscore", description=desc)
            return AnomalyResult(
                is_anomaly=False, score=0.0, method="zscore",
                description="Insufficient variance for Z-score."
            )
        z = abs((current_rate - mean) / std)
        is_anomaly = z > self._z_threshold
        svc = f" in {service}" if service else ""
        desc = (
            f"⚠️ Anomaly detected{svc}: error rate z-score={z:.2f} "
            f"(threshold={self._z_threshold}). "
            f"Current error rate {current_rate:.1%} vs mean {mean:.1%}."
            if is_anomaly
            else f"Error rate z-score={z:.2f} — within normal range."
        )
        return AnomalyResult(is_anomaly=is_anomaly, score=float(z), method="zscore", description=desc)

    def _isolation_forest_check(
        self, error_rate: float, avg_latency: float, log_count: int,
        service: Optional[str]
    ) -> Optional[AnomalyResult]:
        if self._model is None:
            return None
        X = np.array([[error_rate, avg_latency, log_count]])
        pred = self._model.predict(X)[0]  # 1 = normal, -1 = anomaly
        score = float(-self._model.score_samples(X)[0])  # higher = more anomalous
        is_anomaly = pred == -1
        svc = f" in {service}" if service else ""
        desc = (
            f"⚠️ Isolation Forest anomaly{svc}: score={score:.3f}."
            if is_anomaly
            else f"Isolation Forest score={score:.3f} — normal."
        )
        return AnomalyResult(is_anomaly=is_anomaly, score=score, method="isolation_forest", description=desc)
