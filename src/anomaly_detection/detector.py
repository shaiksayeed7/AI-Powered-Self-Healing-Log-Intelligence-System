"""Anomaly detection using Z-score and Isolation Forest."""
import statistics
from collections import deque
from datetime import datetime, timezone
from typing import List, Optional

import numpy as np
from sklearn.ensemble import IsolationForest


class AnomalyDetector:
    """Detects anomalies in log streams using statistical and ML methods."""

    def __init__(self, window_size: int = 100, z_threshold: float = 2.5):
        self._window_size = window_size
        self._z_threshold = z_threshold
        self._window: deque = deque(maxlen=window_size)
        self._iforest: Optional[IsolationForest] = None
        self._iforest_trained = False

    # ------------------------------------------------------------------
    def add_log_entry(self, log_entry: dict) -> None:
        """Update rolling stats with a new log entry."""
        is_error = 1 if log_entry.get("level") in ("ERROR", "CRITICAL") else 0
        latency = log_entry.get("latency_ms") or 0
        self._window.append({"is_error": is_error, "latency": latency,
                              "service": log_entry.get("service", ""),
                              "timestamp": log_entry.get("timestamp", ""),
                              "level": log_entry.get("level", "")})

    def detect_anomalies(self, log_entries: List[dict]) -> List[dict]:
        """Analyse a batch of log entries; return list of anomaly dicts.

        Baseline stats are captured BEFORE ingesting the new batch so that
        a sudden spike in the incoming entries is clearly detectable.
        """
        # Snapshot baseline before adding new entries
        baseline_window = list(self._window)

        for entry in log_entries:
            self.add_log_entry(entry)

        anomalies: List[dict] = []
        anomalies.extend(self._zscore_error_rate(log_entries, baseline_window))
        anomalies.extend(self._zscore_latency(log_entries, baseline_window))
        anomalies.extend(self._isolation_forest(log_entries))
        return anomalies

    def get_error_rate(self) -> float:
        if not self._window:
            return 0.0
        return sum(e["is_error"] for e in self._window) / len(self._window)

    def get_latency_stats(self) -> dict:
        latencies = [e["latency"] for e in self._window if e["latency"] > 0]
        if not latencies:
            return {"mean": 0.0, "std": 0.0, "current": 0.0}
        mean = statistics.mean(latencies)
        std = statistics.stdev(latencies) if len(latencies) > 1 else 0.0
        return {"mean": mean, "std": std, "current": latencies[-1]}

    # ------------------------------------------------------------------
    def _zscore_error_rate(self, entries: List[dict], baseline_window: list) -> List[dict]:
        if len(baseline_window) < 10:
            return []

        baseline_errors = [e["is_error"] for e in baseline_window]
        mean = statistics.mean(baseline_errors)
        std = statistics.stdev(baseline_errors) if len(baseline_errors) > 1 else 0.0

        # Compare incoming batch error rate vs baseline
        batch_errors = [1 if e.get("level") in ("ERROR", "CRITICAL") else 0 for e in entries]
        if not batch_errors:
            return []
        batch_rate = statistics.mean(batch_errors)

        if std == 0:
            # Baseline is uniform; any non-zero batch rate is a spike
            if batch_rate == 0 or batch_rate <= mean:
                return []
            z = float("inf")
        else:
            z = (batch_rate - mean) / std

        if z > self._z_threshold:
            services = [e.get("service", "") for e in entries if e.get("level") in ("ERROR", "CRITICAL")]
            service = max(set(services), key=services.count) if services else "unknown"
            pct = ((batch_rate - mean) / max(mean, 1e-6)) * 100
            severity = "CRITICAL" if z > 4 else "HIGH" if z > 3 else "MEDIUM"
            ts = entries[-1].get("timestamp", datetime.now(timezone.utc).isoformat()) if entries else datetime.now(timezone.utc).isoformat()
            return [{
                "type": "ERROR_SPIKE",
                "severity": severity,
                "service": service,
                "description": f"Error rate increased by {pct:.0f}% vs baseline (z={z:.2f})",
                "timestamp": ts,
                "metrics": {"error_rate": round(batch_rate, 4), "baseline": round(mean, 4), "z_score": round(z, 2) if z != float("inf") else 999},
            }]
        return []

    def _zscore_latency(self, entries: List[dict], baseline_window: list) -> List[dict]:
        baseline_latencies = [e["latency"] for e in baseline_window if e["latency"] > 0]
        if len(baseline_latencies) < 10:
            return []

        mean = statistics.mean(baseline_latencies)
        std = statistics.stdev(baseline_latencies) if len(baseline_latencies) > 1 else 0.0

        # Compare incoming batch latencies vs baseline
        batch_latencies = [e.get("latency_ms") or 0 for e in entries if (e.get("latency_ms") or 0) > 0]
        if not batch_latencies:
            return []
        batch_mean = statistics.mean(batch_latencies)

        if std == 0:
            if batch_mean <= mean:
                return []
            z = float("inf")
        else:
            z = (batch_mean - mean) / std

        if z > self._z_threshold:
            services = [e.get("service", "") for e in entries if (e.get("latency_ms") or 0) > 0]
            service = max(set(services), key=services.count) if services else "unknown"
            severity = "CRITICAL" if z > 4 else "HIGH" if z > 3 else "MEDIUM"
            ts = entries[-1].get("timestamp", datetime.now(timezone.utc).isoformat()) if entries else datetime.now(timezone.utc).isoformat()
            return [{
                "type": "LATENCY_JUMP",
                "severity": severity,
                "service": service,
                "description": f"Latency jumped to {batch_mean:.0f}ms (baseline {mean:.0f}ms, z={z:.2f})",
                "timestamp": ts,
                "metrics": {"current_latency_ms": round(batch_mean, 2), "baseline_ms": round(mean, 2), "z_score": round(z, 2) if z != float("inf") else 999},
            }]
        return []

    def _isolation_forest(self, entries: List[dict]) -> List[dict]:
        if len(self._window) < 20:
            return []

        data = np.array([[e["is_error"], e["latency"]] for e in self._window], dtype=float)
        model = IsolationForest(contamination=0.05, random_state=42, n_estimators=50)
        preds = model.fit_predict(data)

        # Check if the latest entries are anomalous
        recent_preds = preds[-max(1, len(preds) // 10):]
        anomaly_ratio = (recent_preds == -1).mean()

        if anomaly_ratio > 0.5:
            recent_entries = list(self._window)[-max(1, len(self._window) // 10):]
            services = [e["service"] for e in recent_entries]
            service = max(set(services), key=services.count) if services else "unknown"
            ts = entries[-1].get("timestamp", datetime.now(timezone.utc).isoformat()) if entries else datetime.now(timezone.utc).isoformat()
            return [{
                "type": "UNUSUAL_FREQUENCY",
                "severity": "MEDIUM",
                "service": service,
                "description": f"Isolation Forest detected unusual pattern (anomaly ratio: {anomaly_ratio:.0%})",
                "timestamp": ts,
                "metrics": {"anomaly_ratio": round(float(anomaly_ratio), 4)},
            }]
        return []
