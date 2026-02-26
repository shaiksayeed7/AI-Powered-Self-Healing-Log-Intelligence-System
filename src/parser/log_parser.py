"""Log parser: converts raw log lines into structured dicts."""
import re
from typing import Optional
from dateutil import parser as dateutil_parser


# Supported log patterns (ordered from most specific to least)
_PATTERNS = [
    # 2026-02-27T01:23:10 ERROR payment-api DB_CONNECTION_TIMEOUT latency=2500ms
    re.compile(
        r"^(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+Z?)?)"
        r"\s+(?P<level>DEBUG|INFO|WARN|WARNING|ERROR|CRITICAL)"
        r"\s+(?P<service>\S+)"
        r"\s+(?P<message>.+?)(?:\s+latency=(?P<latency>\d+)ms)?$",
        re.IGNORECASE,
    ),
    # [2026-02-27 01:23:10] WARN auth-service "Connection refused" latency=150ms
    re.compile(
        r"^\[(?P<ts>\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2})\]"
        r"\s+(?P<level>DEBUG|INFO|WARN|WARNING|ERROR|CRITICAL)"
        r"\s+(?P<service>\S+)"
        r'\s+"?(?P<message>[^"]+?)"?(?:\s+latency=(?P<latency>\d+)ms)?$',
        re.IGNORECASE,
    ),
    # 2026-02-27T01:23:10.123Z INFO user-service Request processed latency=45ms
    re.compile(
        r"^(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z)"
        r"\s+(?P<level>DEBUG|INFO|WARN|WARNING|ERROR|CRITICAL)"
        r"\s+(?P<service>\S+)"
        r"\s+(?P<message>.+?)(?:\s+latency=(?P<latency>\d+)ms)?$",
        re.IGNORECASE,
    ),
]

_ERROR_KEYWORDS = {
    "DB_CONNECTION_TIMEOUT", "CONNECTION_TIMEOUT", "CONNECTION_REFUSED",
    "TIMEOUT", "OOM", "OUT_OF_MEMORY", "MEMORY_OVERFLOW",
    "AUTH_FAILURE", "AUTHENTICATION_FAILED", "UNAUTHORIZED",
    "NETWORK_ERROR", "DNS_RESOLUTION_FAILED", "SSL_ERROR",
    "CPU_OVERLOAD", "RESOURCE_EXHAUSTED", "DISK_FULL",
    "500", "503", "502", "504",
}


class LogParser:
    """Parses raw log lines into structured dicts."""

    def parse(self, line: str) -> Optional[dict]:
        """Parse a single log line. Returns None if unparseable."""
        line = line.strip()
        if not line:
            return None

        for pattern in _PATTERNS:
            m = pattern.match(line)
            if m:
                return self._build_entry(m, line)

        return None

    # ------------------------------------------------------------------
    def _build_entry(self, m: re.Match, raw: str) -> dict:
        ts_str = m.group("ts")
        try:
            ts = dateutil_parser.parse(ts_str).isoformat()
        except Exception:
            ts = ts_str

        level = m.group("level").upper()
        if level == "WARNING":
            level = "WARN"

        message = m.group("message").strip().strip('"')
        latency_raw = m.group("latency") if "latency" in m.groupdict() else None
        latency_ms = int(latency_raw) if latency_raw else None

        error_type = self._detect_error_type(level, message)

        return {
            "timestamp": ts,
            "level": level,
            "service": m.group("service"),
            "message": message,
            "error_type": error_type,
            "latency_ms": latency_ms,
            "raw": raw,
        }

    @staticmethod
    def _detect_error_type(level: str, message: str) -> Optional[str]:
        if level not in ("ERROR", "CRITICAL"):
            return None
        upper_msg = message.upper().replace(" ", "_")
        for kw in _ERROR_KEYWORDS:
            if kw in upper_msg:
                return kw
        # Return first token as error type for generic errors
        first_token = message.split()[0] if message else None
        return first_token
