"""SentinelAI FastAPI application entry point.

Run with::

    uvicorn sentinelai.main:app --host 0.0.0.0 --port 8000 --reload
"""

from fastapi import FastAPI

from sentinelai.api.routes import router
from sentinelai.storage.database import init_db

app = FastAPI(
    title="SentinelAI – Log Intelligence System",
    description=(
        "AI-Powered Self-Healing Log Intelligence System. "
        "Provides real-time log ingestion, anomaly detection, "
        "failure prediction, root-cause analysis, and auto-fix suggestions."
    ),
    version="0.1.0",
)


@app.on_event("startup")
def _startup():
    init_db()


app.include_router(router, prefix="/api/v1")
