"""
Log Parser – converts raw log lines into structured LogEntry objects.

Supported formats
-----------------
1. Standard syslog / application log:
   ``2026-02-27T01:23:10 ERROR payment-api DB_CONNECTION_TIMEOUT latency=320ms``
2. Apache / Nginx combined access log (best-effort).
3. Generic fallback: keeps the raw line and marks level as UNKNOWN.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class LogEntry:
    """Structured representation of a single log line."""

    raw: str
    timestamp: datetime
    level: str          # INFO | WARN | WARNING | ERROR | CRITICAL | DEBUG | UNKNOWN
    service: str
    message: str
    error_type: Optional[str] = None
    latency_ms: Optional[float] = None
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "level": self.level,
            "service": self.service,
            "message": self.message,
            "error_type": self.error_type,
            "latency_ms": self.latency_ms,
            "extra": self.extra,
        }


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# ISO-8601 / common timestamp variants
_TS_PATTERNS = [
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?",
    r"\d{2}/\w{3}/\d{4}:\d{2}:\d{2}:\d{2} [+-]\d{4}",  # Apache
]
_TS_RE = re.compile("|".join(_TS_PATTERNS))

_LEVEL_RE = re.compile(
    r"\b(DEBUG|INFO|WARN(?:ING)?|ERROR|CRITICAL|FATAL)\b", re.IGNORECASE
)

_LATENCY_RE = re.compile(r"latency[=: ](\d+(?:\.\d+)?)\s*ms", re.IGNORECASE)

_ERROR_TYPE_RE = re.compile(
    r"\b([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)\b"  # UPPER_SNAKE_CASE tokens
)

_TS_FORMATS = [
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M:%S.%f",
    "%d/%b/%Y:%H:%M:%S %z",
]


def _parse_timestamp(ts_str: str) -> datetime:
    ts_str = ts_str.strip()
    # Strip trailing timezone like Z or +00:00
    ts_clean = re.sub(r"Z$", "", ts_str)
    ts_clean = re.sub(r"[+-]\d{2}:?\d{2}$", "", ts_clean).strip()
    for fmt in _TS_FORMATS:
        try:
            return datetime.strptime(ts_clean, fmt)
        except ValueError:
            continue
    # Last resort – try the raw string
    try:
        return datetime.strptime(ts_str, "%d/%b/%Y:%H:%M:%S %z").replace(tzinfo=None)
    except ValueError:
        return datetime.utcnow()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_line(raw: str, default_service: str = "unknown") -> LogEntry:
    """Parse a single raw log line into a :class:`LogEntry`."""
    line = raw.strip()

    # Timestamp
    ts_match = _TS_RE.search(line)
    if ts_match:
        timestamp = _parse_timestamp(ts_match.group())
        remainder = line[ts_match.end():].strip()
    else:
        timestamp = datetime.utcnow()
        remainder = line

    # Log level
    lvl_match = _LEVEL_RE.search(remainder)
    if lvl_match:
        level = lvl_match.group().upper()
        if level == "WARNING":
            level = "WARN"
        if level == "FATAL":
            level = "CRITICAL"
        remainder = (
            remainder[: lvl_match.start()] + remainder[lvl_match.end():]
        ).strip()
    else:
        level = "UNKNOWN"

    # Latency
    lat_match = _LATENCY_RE.search(remainder)
    latency_ms: Optional[float] = None
    if lat_match:
        latency_ms = float(lat_match.group(1))
        remainder = (
            remainder[: lat_match.start()] + remainder[lat_match.end():]
        ).strip()

    # Service name – first token that looks like a service slug
    tokens = remainder.split()
    service = default_service
    if tokens:
        candidate = tokens[0].rstrip(":").rstrip("[").split("[")[0]
        if re.match(r"^[a-zA-Z][a-zA-Z0-9_\-]{0,63}$", candidate):
            service = candidate
            tokens = tokens[1:]

    message = " ".join(tokens).strip() or line

    # Error type (UPPER_SNAKE_CASE)
    error_type: Optional[str] = None
    et_match = _ERROR_TYPE_RE.search(message)
    if et_match:
        error_type = et_match.group(1)

    return LogEntry(
        raw=raw,
        timestamp=timestamp,
        level=level,
        service=service,
        message=message,
        error_type=error_type,
        latency_ms=latency_ms,
    )
