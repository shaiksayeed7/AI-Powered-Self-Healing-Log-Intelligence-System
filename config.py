"""
SentinelAI – central configuration.
All tuneable parameters live here so they can be overridden via environment
variables without touching application code.
"""

import os

# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./sentinelai.db")

# ---------------------------------------------------------------------------
# Log ingestion
# ---------------------------------------------------------------------------
LOG_WATCH_PATHS: list[str] = os.getenv(
    "LOG_WATCH_PATHS", "./logs"
).split(",")

# ---------------------------------------------------------------------------
# Anomaly detection
# ---------------------------------------------------------------------------
# Rolling window size (number of log events) used for z-score calculation
ANOMALY_WINDOW_SIZE: int = int(os.getenv("ANOMALY_WINDOW_SIZE", "100"))
# Z-score threshold above which a data point is flagged as anomalous
ZSCORE_THRESHOLD: float = float(os.getenv("ZSCORE_THRESHOLD", "3.0"))
# Isolation Forest contamination parameter
ISOLATION_FOREST_CONTAMINATION: float = float(
    os.getenv("ISOLATION_FOREST_CONTAMINATION", "0.05")
)

# ---------------------------------------------------------------------------
# Failure prediction
# ---------------------------------------------------------------------------
# Number of recent error-rate samples used for velocity / trend calculation
PREDICTION_WINDOW: int = int(os.getenv("PREDICTION_WINDOW", "10"))
# Error-rate growth percentage that triggers a "predicted crash" warning
CRASH_VELOCITY_THRESHOLD: float = float(
    os.getenv("CRASH_VELOCITY_THRESHOLD", "50.0")
)
# Minutes ahead the prediction claims a crash may happen
PREDICTION_HORIZON_MINUTES: int = int(
    os.getenv("PREDICTION_HORIZON_MINUTES", "12")
)

# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
API_PORT: int = int(os.getenv("API_PORT", "8000"))
