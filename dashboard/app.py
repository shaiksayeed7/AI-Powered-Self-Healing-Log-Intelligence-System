"""Streamlit dashboard for SentinelAI."""
import time
import requests
import streamlit as st

API_BASE = "http://localhost:8000"

st.set_page_config(page_title="SentinelAI", page_icon="🛡️", layout="wide")
st.title("🛡️ SentinelAI - Log Intelligence Dashboard")

# ------------------------------------------------------------------
# Sidebar
# ------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Controls")
    refresh_rate = st.slider("Refresh rate (seconds)", min_value=5, max_value=60, value=15)
    st.divider()
    service_filter = st.text_input("Service filter (leave blank for all)", value="")
    log_level_filter = st.selectbox("Log level filter", ["ALL", "INFO", "WARN", "ERROR", "CRITICAL"])
    st.divider()
    if st.button("🔄 Refresh now"):
        st.rerun()


# ------------------------------------------------------------------
# Helper functions
# ------------------------------------------------------------------
def _get(path: str, params: dict | None = None):
    try:
        r = requests.get(f"{API_BASE}{path}", params=params, timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        return None


def _severity_badge(severity: str) -> str:
    colours = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢"}
    return f"{colours.get(severity, '⚪')} {severity}"


# ------------------------------------------------------------------
# Fetch data
# ------------------------------------------------------------------
stats = _get("/dashboard/stats") or {}
log_params = {"limit": 200}
if service_filter:
    log_params["service"] = service_filter
logs = _get("/logs", log_params) or []
if log_level_filter != "ALL":
    logs = [l for l in logs if l.get("level") == log_level_filter]

anomalies = _get("/anomalies", {"limit": 50}) or []
predictions = _get("/predictions") or []

# Fetch fixes from the last RCA if anomalies exist
fixes = None
if anomalies:
    # Build a small log text from the most recent logs for the /analyze endpoint
    recent_raw = "\n".join(l.get("raw", "") for l in logs[-20:] if l.get("raw"))
    if recent_raw:
        try:
            r = requests.post(f"{API_BASE}/analyze", json={"log_text": recent_raw}, timeout=10)
            if r.ok:
                fixes = r.json().get("fixes")
        except Exception:
            pass

# ------------------------------------------------------------------
# Tabs
# ------------------------------------------------------------------
tab1, tab2, tab3, tab4, tab5 = st.tabs(
    ["📊 Overview", "📋 Live Logs", "⚠️ Anomalies", "🔮 Predictions", "🔧 Auto-Fix"]
)

# ---- Tab 1: Overview ----
with tab1:
    connected = stats is not None and bool(stats)
    if not connected:
        st.error("⚠️ Cannot connect to SentinelAI API at http://localhost:8000. Is the server running?")
    else:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("📄 Total Logs", stats.get("total_logs", 0))
        c2.metric("🚨 Error Rate", f"{stats.get('error_rate', 0):.1%}")
        c3.metric("⚠️ Active Anomalies", stats.get("active_anomalies", 0))
        c4.metric("🔮 Predictions", stats.get("predictions", 0))

        svcs = stats.get("services", [])
        if svcs:
            st.subheader("Monitored Services")
            st.write(", ".join(sorted(svcs)))

# ---- Tab 2: Live Logs ----
with tab2:
    if not logs:
        st.info("No logs available. Make sure the API server is running and the log file exists.")
    else:
        import pandas as pd
        df = pd.DataFrame(logs)[["timestamp", "level", "service", "message", "latency_ms", "error_type"]].copy()

        def _colour(row):
            colours = {"ERROR": "background-color: #ffe0e0", "CRITICAL": "background-color: #ffb3b3",
                       "WARN": "background-color: #fff3cd", "INFO": ""}
            c = colours.get(row.get("level", ""), "")
            return [c] * len(row)

        st.dataframe(df.style.apply(_colour, axis=1), use_container_width=True, height=500)

# ---- Tab 3: Anomalies ----
with tab3:
    if not anomalies:
        st.success("✅ No anomalies detected.")
    else:
        for a in reversed(anomalies):
            with st.expander(f"{_severity_badge(a.get('severity','?'))} {a.get('type')} — {a.get('service')} @ {a.get('timestamp','')}", expanded=False):
                st.write(a.get("description"))
                st.json(a.get("metrics", {}))

# ---- Tab 4: Predictions ----
with tab4:
    if not predictions:
        st.success("✅ No failure predictions at this time.")
    else:
        for p in reversed(predictions):
            conf = p.get("confidence", 0)
            svc = p.get("service", "?")
            ttf = p.get("time_to_failure_minutes")
            cause = p.get("cause", "")
            with st.expander(f"🔮 {svc} — {cause} (confidence: {conf:.0%})", expanded=True):
                st.progress(min(conf, 1.0))
                if ttf:
                    st.warning(f"Estimated time to failure: **{ttf} minutes**")
                st.write("**Indicators:**")
                for ind in p.get("indicators", []):
                    st.write(f"- {ind}")

# ---- Tab 5: Auto-Fix ----
with tab5:
    if fixes is None:
        st.info("No fix suggestions available. Anomalies must be detected first.")
    else:
        st.subheader(f"Root cause: **{fixes.get('cause', '?')}** — Severity: {_severity_badge(fixes.get('severity','?'))}")
        for action in sorted(fixes.get("actions", []), key=lambda x: x.get("priority", 99)):
            pri = action.get("priority", "?")
            act = action.get("action", "")
            cmd = action.get("command", "")
            with st.expander(f"#{pri} {act}", expanded=pri == 1):
                if cmd:
                    st.code(cmd, language="bash")
                else:
                    st.write("_(manual action required)_")
        if fixes.get("auto_executable"):
            st.success("✅ These actions can be executed automatically.")
        else:
            st.warning("⚠️ Manual review required before executing these actions.")

# ------------------------------------------------------------------
# Auto-refresh
# ------------------------------------------------------------------
time.sleep(refresh_rate)
st.rerun()
