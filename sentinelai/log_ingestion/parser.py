"""Intelligent Log Parsing Engine.

Converts raw log text into structured JSON records.

Supported formats
-----------------
* Standard syslog / application format::

    2026-02-27T01:23:10 ERROR payment-api DB_CONNECTION_TIMEOUT latency=320ms

* Python logging format::

    2026-02-27 01:23:10,123 - payment-api - ERROR - message text

* Generic fallback: timestamp + level anywhere in the line.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional


# ── Compiled patterns ─────────────────────────────────────────────────────────

_ISO_TS = r"(?P<timestamp>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?)"
_LEVEL = r"(?P<level>DEBUG|INFO|WARN(?:ING)?|ERROR|CRITICAL|FATAL)"
_SERVICE = r"(?P<service>[A-Za-z0-9_\-]+)"
_LATENCY = r"latency=(?P<latency>\d+(?:\.\d+)?)\s*ms"
_ERROR_CODE = r"(?P<error_code>[A-Z][A-Z0-9_]{3,})"

# Full structured pattern: <ts> <level> <service> [error_code] [latency=Nms] <message>
_FULL_RE = re.compile(
    rf"{_ISO_TS}\s+{_LEVEL}\s+{_SERVICE}"
    rf"(?:\s+{_ERROR_CODE})?"
    rf"(?:\s+{_LATENCY})?"
    rf"(?:\s+(?P<message>.+))?",
    re.IGNORECASE,
)

# Python logging: <ts> - <service> - <level> - <message>
_PYTHON_RE = re.compile(
    rf"{_ISO_TS}\s+-\s+{_SERVICE}\s+-\s+{_LEVEL}\s+-\s+(?P<message>.+)",
    re.IGNORECASE,
)

# Fallback: just extract timestamp + level
_FALLBACK_RE = re.compile(rf"{_ISO_TS}.*{_LEVEL}", re.IGNORECASE)

_LATENCY_INLINE = re.compile(r"latency=(\d+(?:\.\d+)?)\s*ms", re.IGNORECASE)
_ERROR_CODE_INLINE = re.compile(r"\b([A-Z][A-Z0-9_]{3,})\b")


def _parse_timestamp(raw: str) -> str:
    """Normalise a timestamp string to ISO-8601 format."""
    raw = raw.replace(",", ".").replace(" ", "T", 1)
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            return datetime.strptime(raw, fmt).isoformat()
        except ValueError:
            continue
    return raw


def parse_log_line(line: str) -> Optional[dict]:
    """Parse a single log line into a structured dict.

    Parameters
    ----------
    line:
        Raw log line text.

    Returns
    -------
    dict or None
        Structured log record, or *None* if the line cannot be parsed.

    Example record::

        {
            "timestamp": "2026-02-27T01:23:10",
            "level": "ERROR",
            "service": "payment-api",
            "error_code": "DB_CONNECTION_TIMEOUT",
            "latency_ms": 320.0,
            "message": "DB_CONNECTION_TIMEOUT latency=320ms",
            "raw": "<original line>"
        }
    """
    line = line.strip()
    if not line:
        return None

    record: dict = {"raw": line}

    # Try Python logging format first (contains " - " separators)
    m = _PYTHON_RE.match(line)
    if m:
        record["timestamp"] = _parse_timestamp(m.group("timestamp"))
        record["level"] = m.group("level").upper()
        record["service"] = m.group("service")
        record["message"] = m.group("message").strip()
        _enrich(record, record["message"])
        return record

    # Try full structured pattern
    m = _FULL_RE.match(line)
    if m:
        record["timestamp"] = _parse_timestamp(m.group("timestamp"))
        record["level"] = m.group("level").upper()
        record["service"] = m.group("service")
        if m.group("error_code"):
            record["error_code"] = m.group("error_code")
        if m.group("latency"):
            record["latency_ms"] = float(m.group("latency"))
        raw_msg = m.group("message") or ""
        record["message"] = raw_msg.strip()
        _enrich(record, line)
        return record

    # Fallback: extract what we can
    m = _FALLBACK_RE.search(line)
    if m:
        record["timestamp"] = _parse_timestamp(m.group("timestamp"))
        record["level"] = m.group("level").upper()
        record["service"] = "unknown"
        record["message"] = line
        _enrich(record, line)
        return record

    return None


def _enrich(record: dict, text: str) -> None:
    """Fill latency_ms and error_code from *text* if not already set."""
    if "latency_ms" not in record:
        m = _LATENCY_INLINE.search(text)
        if m:
            record["latency_ms"] = float(m.group(1))

    if "error_code" not in record:
        # Pick the first ALL_CAPS token that looks like an error code
        candidates = _ERROR_CODE_INLINE.findall(text)
        skip = {"ERROR", "WARN", "WARNING", "DEBUG", "INFO", "CRITICAL", "FATAL"}
        for c in candidates:
            if c not in skip:
                record["error_code"] = c
                break
