"""
SentinelAI – Streamlit Dashboard.

Run with:
    streamlit run dashboard/app.py
"""

from __future__ import annotations

import sys
import os

# Ensure the project root is on the path when running from dashboard/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json
import time
from datetime import datetime, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="SentinelAI – Log Intelligence",
    page_icon="🛡️",
    layout="wide",
)

# ---------------------------------------------------------------------------
# API base URL (configurable via env var)
# ---------------------------------------------------------------------------

API_BASE = os.getenv("SENTINELAI_API_URL", "http://localhost:8000")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@st.cache_data(ttl=5)
def fetch_logs(limit: int = 200, service: str | None = None) -> list[dict]:
    try:
        import httpx
        params: dict = {"limit": limit}
        if service:
            params["service"] = service
        resp = httpx.get(f"{API_BASE}/api/logs", params=params, timeout=5)
        resp.raise_for_status()
        return resp.json().get("entries", [])
    except Exception:
        return []


@st.cache_data(ttl=5)
def fetch_anomalies(limit: int = 100) -> list[dict]:
    try:
        import httpx
        resp = httpx.get(f"{API_BASE}/api/anomalies", params={"limit": limit}, timeout=5)
        resp.raise_for_status()
        return resp.json().get("anomalies", [])
    except Exception:
        return []


@st.cache_data(ttl=5)
def fetch_predictions(limit: int = 50) -> list[dict]:
    try:
        import httpx
        resp = httpx.get(f"{API_BASE}/api/predictions", params={"limit": limit}, timeout=5)
        resp.raise_for_status()
        return resp.json().get("predictions", [])
    except Exception:
        return []


def ingest_line(raw: str, service: str) -> dict:
    try:
        import httpx
        resp = httpx.post(
            f"{API_BASE}/api/logs/ingest",
            json={"raw": raw, "service": service or None},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        return {"error": str(exc)}


def get_fix(service: str) -> dict:
    try:
        import httpx
        resp = httpx.get(f"{API_BASE}/api/fix/{service}", timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("🛡️ SentinelAI")
    st.caption("AI-Powered Self-Healing Log Intelligence")
    st.divider()

    page = st.radio(
        "Navigation",
        ["📊 Overview", "📋 Log Explorer", "⚠️ Anomalies", "🔮 Predictions", "🩺 RCA & Fixes", "📤 Ingest Logs"],
    )

    st.divider()
    auto_refresh = st.checkbox("Auto-refresh (5s)", value=False)
    if auto_refresh:
        time.sleep(5)
        st.rerun()


# ---------------------------------------------------------------------------
# Overview page
# ---------------------------------------------------------------------------

if page == "📊 Overview":
    st.title("📊 System Overview")

    logs = fetch_logs(limit=500)
    anomalies = fetch_anomalies(limit=200)
    predictions = fetch_predictions(limit=50)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Log Entries", len(logs))
    col2.metric("Anomalies Detected", len(anomalies))
    active_crashes = sum(1 for p in predictions if p.get("predicted_crash"))
    col3.metric("⚠️ Predicted Crashes", active_crashes)
    if logs:
        error_count = sum(1 for l in logs if l.get("level") in ("ERROR", "CRITICAL"))
        col4.metric("Error Rate", f"{error_count / len(logs) * 100:.1f}%")
    else:
        col4.metric("Error Rate", "N/A")

    st.divider()

    if logs:
        df = pd.DataFrame(logs)
        df["timestamp"] = pd.to_datetime(df["timestamp"])

        col_left, col_right = st.columns(2)

        with col_left:
            st.subheader("Log Level Distribution")
            level_counts = df["level"].value_counts().reset_index()
            level_counts.columns = ["level", "count"]
            fig = px.pie(level_counts, names="level", values="count",
                         color_discrete_map={
                             "ERROR": "#ef4444",
                             "CRITICAL": "#7f1d1d",
                             "WARN": "#f59e0b",
                             "INFO": "#3b82f6",
                             "DEBUG": "#6b7280",
                             "UNKNOWN": "#9ca3af",
                         })
            st.plotly_chart(fig, use_container_width=True)

        with col_right:
            st.subheader("Top Services by Log Volume")
            svc_counts = df["service"].value_counts().head(10).reset_index()
            svc_counts.columns = ["service", "count"]
            fig2 = px.bar(svc_counts, x="service", y="count", color="count",
                          color_continuous_scale="Blues")
            st.plotly_chart(fig2, use_container_width=True)

        st.subheader("Log Volume Over Time")
        df_sorted = df.sort_values("timestamp")
        df_sorted["minute"] = df_sorted["timestamp"].dt.floor("1min")
        timeline = df_sorted.groupby(["minute", "level"]).size().reset_index(name="count")
        fig3 = px.bar(timeline, x="minute", y="count", color="level",
                      color_discrete_map={
                          "ERROR": "#ef4444",
                          "CRITICAL": "#7f1d1d",
                          "WARN": "#f59e0b",
                          "INFO": "#3b82f6",
                          "DEBUG": "#6b7280",
                      })
        st.plotly_chart(fig3, use_container_width=True)
    else:
        st.info("No logs ingested yet. Use the 'Ingest Logs' tab to add some log lines.")


# ---------------------------------------------------------------------------
# Log Explorer
# ---------------------------------------------------------------------------

elif page == "📋 Log Explorer":
    st.title("📋 Log Explorer")

    col1, col2 = st.columns([3, 1])
    with col1:
        service_filter = st.text_input("Filter by service", placeholder="e.g. payment-api")
    with col2:
        limit = st.selectbox("Max rows", [50, 100, 200, 500], index=1)

    logs = fetch_logs(limit=limit, service=service_filter or None)

    if logs:
        df = pd.DataFrame(logs)
        df["timestamp"] = pd.to_datetime(df["timestamp"])

        level_color = {
            "ERROR": "🔴",
            "CRITICAL": "🔴",
            "WARN": "🟡",
            "INFO": "🟢",
            "DEBUG": "⚪",
            "UNKNOWN": "⚪",
        }
        df["🔔"] = df["level"].map(lambda x: level_color.get(x, "⚪"))
        display_cols = ["🔔", "timestamp", "level", "service", "message", "error_type", "latency_ms"]
        st.dataframe(df[display_cols], use_container_width=True, height=500)
    else:
        st.info("No log entries found.")


# ---------------------------------------------------------------------------
# Anomalies
# ---------------------------------------------------------------------------

elif page == "⚠️ Anomalies":
    st.title("⚠️ Anomaly Detection")

    anomalies = fetch_anomalies(limit=200)

    if anomalies:
        df = pd.DataFrame(anomalies)
        df["detected_at"] = pd.to_datetime(df["detected_at"])

        st.metric("Total Anomalies", len(df))
        st.divider()

        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Anomalies by Service")
            svc = df["service"].value_counts().reset_index()
            svc.columns = ["service", "count"]
            fig = px.bar(svc.head(10), x="service", y="count", color="count",
                         color_continuous_scale="Reds")
            st.plotly_chart(fig, use_container_width=True)

        with col2:
            st.subheader("Z-score Distribution")
            zscores = df["zscore"].dropna()
            if not zscores.empty:
                fig2 = px.histogram(zscores, nbins=30, title="Z-score distribution")
                st.plotly_chart(fig2, use_container_width=True)
            else:
                st.info("No z-score data yet.")

        st.subheader("Recent Anomalies")
        display = df[["detected_at", "service", "level", "message", "zscore", "reason"]].head(100)
        st.dataframe(display, use_container_width=True)
    else:
        st.info("No anomalies detected yet.")


# ---------------------------------------------------------------------------
# Predictions
# ---------------------------------------------------------------------------

elif page == "🔮 Predictions":
    st.title("🔮 Failure Predictions")

    predictions = fetch_predictions(limit=100)

    if predictions:
        df = pd.DataFrame(predictions)
        df["predicted_at"] = pd.to_datetime(df["predicted_at"])

        crash_df = df[df["predicted_crash"]]
        st.metric("⚠️ Services at Risk", crash_df["service"].nunique())

        if not crash_df.empty:
            st.error("### ⚠️ Active Crash Predictions")
            for _, row in crash_df.iterrows():
                with st.expander(
                    f"🚨 {row['service']} – Crash predicted in ~{row['estimated_minutes']} min "
                    f"(confidence: {row['confidence']*100:.0f}%)"
                ):
                    st.write(f"**Cause:** {row['cause']}")
                    st.write(f"**Error velocity:** {row['error_velocity_pct']:.1f}%")
                    st.write(f"**Predicted at:** {row['predicted_at']}")

        st.subheader("All Predictions")
        st.dataframe(
            df[["predicted_at", "service", "predicted_crash", "confidence", "estimated_minutes", "cause"]],
            use_container_width=True,
        )
    else:
        st.info("No crash predictions recorded yet.")


# ---------------------------------------------------------------------------
# RCA & Fixes
# ---------------------------------------------------------------------------

elif page == "🩺 RCA & Fixes":
    st.title("🩺 Root Cause Analysis & Fix Suggestions")

    service = st.text_input("Service name", placeholder="e.g. payment-api")

    if st.button("🔍 Analyse") and service:
        fix = get_fix(service)

        if "error" in fix:
            st.error(f"Error: {fix['error']}")
        else:
            if fix.get("probable_cause"):
                st.warning(f"**Probable Cause:** {fix['probable_cause']}")
                st.info(f"**Matched Rule:** {fix.get('rule_name', 'N/A')}")
            else:
                st.success("No clear root cause identified – system appears healthy.")

            if fix.get("actions"):
                st.subheader("Recommended Actions")
                for action in fix["actions"]:
                    icon = "🤖" if action["auto_executable"] else "👤"
                    with st.expander(f"Step {action['step']}: {action['description']}"):
                        if action.get("command"):
                            st.code(action["command"], language="bash")
                        st.write(
                            f"{icon} {'Auto-executable (requires approval)' if action['auto_executable'] else 'Manual action required'}"
                        )


# ---------------------------------------------------------------------------
# Ingest Logs
# ---------------------------------------------------------------------------

elif page == "📤 Ingest Logs":
    st.title("📤 Ingest Log Lines")

    tab1, tab2 = st.tabs(["Single Line", "Batch / File"])

    with tab1:
        raw_line = st.text_area(
            "Raw log line",
            placeholder='2026-02-27T01:23:10 ERROR payment-api DB_CONNECTION_TIMEOUT latency=320ms',
            height=100,
        )
        svc = st.text_input("Default service name (optional)", placeholder="payment-api")

        if st.button("Ingest"):
            if raw_line.strip():
                result = ingest_line(raw_line, svc)
                if "error" in result:
                    st.error(f"Error: {result['error']}")
                else:
                    st.success("✅ Log line ingested!")
                    col1, col2 = st.columns(2)
                    with col1:
                        st.subheader("Parsed Entry")
                        st.json(result["entry"])
                    with col2:
                        st.subheader("Anomaly Result")
                        if result["anomaly"]["is_anomaly"]:
                            st.warning("⚠️ Anomaly detected!")
                        else:
                            st.success("✅ Normal")
                        st.json(result["anomaly"])

                    if result["prediction"]["predicted_crash"]:
                        st.error(
                            f"🚨 Crash predicted for '{result['prediction']['service']}' "
                            f"in ~{result['prediction']['estimated_minutes']} min "
                            f"(confidence: {result['prediction']['confidence']*100:.0f}%)"
                        )
            else:
                st.warning("Please enter a log line.")

    with tab2:
        uploaded = st.file_uploader("Upload a .log file", type=["log", "txt"])
        svc2 = st.text_input("Default service name", placeholder="my-service", key="batch_svc")

        if uploaded and st.button("Ingest File"):
            lines = uploaded.read().decode("utf-8", errors="replace").splitlines()
            lines = [l for l in lines if l.strip()]
            st.info(f"Ingesting {len(lines)} lines…")

            import httpx
            try:
                resp = httpx.post(
                    f"{API_BASE}/api/logs/batch",
                    json={"lines": lines, "service": svc2 or None},
                    timeout=60,
                )
                resp.raise_for_status()
                data = resp.json()
                anomaly_count = sum(
                    1 for r in data.get("results", []) if r["anomaly"]["is_anomaly"]
                )
                st.success(
                    f"✅ Ingested {data['processed']} lines. "
                    f"Anomalies detected: {anomaly_count}"
                )
            except Exception as exc:
                st.error(f"Error: {exc}")
