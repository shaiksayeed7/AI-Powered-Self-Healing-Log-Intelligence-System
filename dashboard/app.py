"""SentinelAI – Streamlit Dashboard.

Run with::

    streamlit run dashboard/app.py
"""

from __future__ import annotations

import time
from datetime import datetime

import httpx
import streamlit as st

API_BASE = "http://localhost:8000/api/v1"

st.set_page_config(
    page_title="SentinelAI Dashboard",
    page_icon="🛡️",
    layout="wide",
)

st.title("🛡️ SentinelAI – Log Intelligence Dashboard")
st.caption("AI-Powered Self-Healing Log Intelligence System")

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Controls")
    auto_refresh = st.checkbox("Auto-refresh (5 s)", value=False)
    st.divider()
    st.subheader("📤 Ingest Log Line")
    log_input = st.text_area(
        "Paste a raw log line",
        placeholder='2026-02-27T01:23:10 ERROR payment-api DB_CONNECTION_TIMEOUT latency=320ms',
        height=80,
    )
    if st.button("Ingest", type="primary"):
        if log_input.strip():
            try:
                resp = httpx.post(f"{API_BASE}/ingest/line", json={"line": log_input}, timeout=10)
                if resp.status_code == 200:
                    st.success("✅ Ingested successfully")
                    st.json(resp.json())
                else:
                    st.error(f"❌ {resp.status_code}: {resp.text}")
            except Exception as exc:
                st.error(f"Connection error: {exc}")
        else:
            st.warning("Enter a log line first.")

    st.divider()
    st.subheader("📂 Ingest Log File")
    file_path = st.text_input("Log file path", placeholder="/var/log/app.log")
    if st.button("Process File"):
        if file_path.strip():
            try:
                resp = httpx.post(f"{API_BASE}/ingest/file", json={"path": file_path}, timeout=60)
                if resp.status_code == 200:
                    st.success("✅ File processed")
                    st.json(resp.json())
                else:
                    st.error(f"❌ {resp.status_code}: {resp.text}")
            except Exception as exc:
                st.error(f"Connection error: {exc}")
        else:
            st.warning("Enter a file path first.")


# ── Helper ────────────────────────────────────────────────────────────────────

def _fetch(endpoint: str, params: dict | None = None) -> list | None:
    try:
        resp = httpx.get(f"{API_BASE}{endpoint}", params=params, timeout=5)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


# ── Main content ──────────────────────────────────────────────────────────────

tab_overview, tab_logs, tab_anomalies, tab_predictions, tab_rca = st.tabs(
    ["📊 Overview", "📋 Logs", "⚠️ Anomalies", "🔮 Predictions", "🔍 RCA"]
)

# ── Overview ──────────────────────────────────────────────────────────────────
with tab_overview:
    logs = _fetch("/logs", {"limit": 500}) or []
    anomalies = _fetch("/anomalies", {"limit": 100}) or []
    predictions = _fetch("/predictions", {"limit": 100}) or []
    rca_results = _fetch("/rca", {"limit": 50}) or []

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("📋 Log Records", len(logs))
    c2.metric("⚠️ Anomalies Detected", sum(1 for a in anomalies if a.get("is_anomaly")))
    c3.metric("🔮 Predictions", sum(1 for p in predictions if p.get("failure_likely")))
    c4.metric("🔍 RCA Results", len(rca_results))

    if anomalies:
        import pandas as pd
        st.subheader("Recent Anomaly Timeline")
        df = pd.DataFrame(anomalies[:20])
        if "detected_at" in df.columns:
            df = df.sort_values("detected_at")
        st.dataframe(df[["detected_at", "service", "is_anomaly", "method", "description"]].head(20),
                     use_container_width=True)

# ── Logs ──────────────────────────────────────────────────────────────────────
with tab_logs:
    import pandas as pd

    col1, col2 = st.columns(2)
    service_filter = col1.text_input("Filter by service", key="log_svc")
    level_filter = col2.selectbox(
        "Filter by level", ["", "ERROR", "WARN", "INFO", "DEBUG", "CRITICAL"],
        key="log_lvl",
    )
    params: dict = {"limit": 200}
    if service_filter:
        params["service"] = service_filter
    if level_filter:
        params["level"] = level_filter

    logs = _fetch("/logs", params) or []
    if logs:
        df = pd.DataFrame(logs)
        st.dataframe(df, use_container_width=True)
    else:
        st.info("No log records yet. Ingest some logs using the sidebar.")

# ── Anomalies ─────────────────────────────────────────────────────────────────
with tab_anomalies:
    anomalies = _fetch("/anomalies") or []
    if anomalies:
        import pandas as pd
        df = pd.DataFrame(anomalies)
        active = df[df["is_anomaly"] == 1]
        if not active.empty:
            st.error(f"🚨 {len(active)} active anomalies detected!")
            st.dataframe(active, use_container_width=True)
        else:
            st.success("✅ No active anomalies.")
        with st.expander("All anomaly records"):
            st.dataframe(df, use_container_width=True)
    else:
        st.info("No anomaly records yet.")

# ── Predictions ───────────────────────────────────────────────────────────────
with tab_predictions:
    predictions = _fetch("/predictions") or []
    if predictions:
        import pandas as pd
        df = pd.DataFrame(predictions)
        critical = df[df["failure_likely"] == 1]
        if not critical.empty:
            st.warning(f"⚠️ {len(critical)} failure prediction(s) flagged!")
            for _, row in critical.iterrows():
                mins = row.get("minutes_to_failure")
                mins_str = f"~{mins:.0f} min" if mins else "soon"
                st.error(
                    f"**{row['service']}** — Predicted crash in {mins_str} "
                    f"(confidence: {row['confidence']:.0%}) — {row['cause']}"
                )
        else:
            st.success("✅ No imminent failures predicted.")
        with st.expander("All prediction records"):
            st.dataframe(df, use_container_width=True)
    else:
        st.info("No prediction records yet.")

# ── RCA ───────────────────────────────────────────────────────────────────────
with tab_rca:
    rca_results = _fetch("/rca") or []
    if rca_results:
        import pandas as pd
        df = pd.DataFrame(rca_results)
        st.dataframe(df, use_container_width=True)
    else:
        st.info("No RCA results yet.")

    st.divider()
    st.subheader("🔍 Manual RCA + Fix Suggestion")
    codes_input = st.text_input(
        "Error codes (comma-separated)",
        placeholder="DB_CONNECTION_TIMEOUT, CONNECTION_POOL_EXHAUSTED",
    )
    svc_input = st.text_input("Service name", placeholder="payment-api")
    if st.button("Analyse"):
        if codes_input:
            codes = [c.strip() for c in codes_input.split(",") if c.strip()]
            try:
                resp = httpx.post(
                    f"{API_BASE}/analyse",
                    json=codes,
                    params={"service": svc_input or "unknown"},
                    timeout=10,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("rca"):
                        st.subheader("Root Cause Analysis")
                        st.json(data["rca"])
                    if data.get("fix_suggestion"):
                        st.subheader("Recommended Actions")
                        st.text(data["fix_suggestion"]["summary"])
                else:
                    st.error(f"❌ {resp.status_code}: {resp.text}")
            except Exception as exc:
                st.error(f"Connection error: {exc}")
        else:
            st.warning("Enter at least one error code.")

# ── Auto-refresh ──────────────────────────────────────────────────────────────
if auto_refresh:
    time.sleep(5)
    st.rerun()
