"""Global configuration for SentinelAI."""

import os

# ── Database ──────────────────────────────────────────────────────────────────
DATABASE_URL: str = os.getenv("SENTINEL_DB_URL", "sentinel.db")

# ── Anomaly Detection ─────────────────────────────────────────────────────────
# Rolling window size (number of 1-minute buckets)
ANOMALY_WINDOW_SIZE: int = int(os.getenv("ANOMALY_WINDOW_SIZE", "10"))
# Z-score threshold above which a data point is considered anomalous
ANOMALY_Z_THRESHOLD: float = float(os.getenv("ANOMALY_Z_THRESHOLD", "2.5"))
# Minimum samples required before running Isolation Forest
ISOLATION_FOREST_MIN_SAMPLES: int = int(os.getenv("ISOLATION_FOREST_MIN_SAMPLES", "20"))

# ── Failure Prediction ────────────────────────────────────────────────────────
# Minimum number of data points required to make a prediction
PREDICTION_MIN_SAMPLES: int = int(os.getenv("PREDICTION_MIN_SAMPLES", "5"))
# Look-ahead minutes for failure window
PREDICTION_LOOKAHEAD_MINUTES: int = int(os.getenv("PREDICTION_LOOKAHEAD_MINUTES", "15"))

# ── Log Streamer ──────────────────────────────────────────────────────────────
LOG_POLL_INTERVAL_SECONDS: float = float(os.getenv("LOG_POLL_INTERVAL_SECONDS", "1.0"))

# ── API ───────────────────────────────────────────────────────────────────────
API_HOST: str = os.getenv("SENTINEL_HOST", "0.0.0.0")
API_PORT: int = int(os.getenv("SENTINEL_PORT", "8000"))
