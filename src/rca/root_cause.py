"""Rule-based root cause analysis."""
from typing import List


_RULES = [
    {
        "id": "DB_OVERLOAD",
        "name": "DB overload",
        "severity": "HIGH",
        "description": "Database connection pool exhausted causing cascading failures.",
        "checks": lambda anomalies, logs: (
            _has_error_type(logs, {"DB_CONNECTION_TIMEOUT", "CONNECTION_TIMEOUT", "CONNECTION_REFUSED"})
            and (_error_spike_present(anomalies) or _high_error_rate(logs, 0.3))
        ),
    },
    {
        "id": "MEMORY_SATURATION",
        "name": "Memory saturation",
        "severity": "HIGH",
        "description": "Memory saturation causing high latency and OOM errors.",
        "checks": lambda anomalies, logs: (
            _has_error_type(logs, {"OOM", "OUT_OF_MEMORY", "MEMORY_OVERFLOW"})
            or (_latency_jump_present(anomalies) and _has_level(logs, "CRITICAL"))
        ),
    },
    {
        "id": "AUTH_FAILURE",
        "name": "Auth service failure",
        "severity": "HIGH",
        "description": "Authentication service is failing, blocking user requests.",
        "checks": lambda anomalies, logs: (
            _has_error_type(logs, {"AUTH_FAILURE", "AUTHENTICATION_FAILED", "UNAUTHORIZED"})
            or _service_error_rate(logs, "auth-service", 0.3)
        ),
    },
    {
        "id": "NETWORK_ISSUE",
        "name": "Network connectivity issue",
        "severity": "MEDIUM",
        "description": "Network timeouts and DNS resolution failures detected.",
        "checks": lambda anomalies, logs: (
            _has_error_type(logs, {"NETWORK_ERROR", "DNS_RESOLUTION_FAILED", "SSL_ERROR", "CONNECTION_REFUSED"})
        ),
    },
    {
        "id": "RESOURCE_EXHAUSTION",
        "name": "Resource exhaustion",
        "severity": "CRITICAL",
        "description": "CPU/disk resources are exhausted, causing widespread failures.",
        "checks": lambda anomalies, logs: (
            _has_error_type(logs, {"CPU_OVERLOAD", "RESOURCE_EXHAUSTED", "DISK_FULL"})
        ),
    },
]


def _has_error_type(logs: List[dict], types: set) -> bool:
    return any(l.get("error_type", "").upper() in types for l in logs)


def _error_spike_present(anomalies: List[dict]) -> bool:
    return any(a.get("type") == "ERROR_SPIKE" for a in anomalies)


def _latency_jump_present(anomalies: List[dict]) -> bool:
    return any(a.get("type") == "LATENCY_JUMP" for a in anomalies)


def _high_error_rate(logs: List[dict], threshold: float) -> bool:
    if not logs:
        return False
    errors = sum(1 for l in logs if l.get("level") in ("ERROR", "CRITICAL"))
    return errors / len(logs) >= threshold


def _service_error_rate(logs: List[dict], service: str, threshold: float) -> bool:
    svc_logs = [l for l in logs if l.get("service") == service]
    return _high_error_rate(svc_logs, threshold)


def _has_level(logs: List[dict], level: str) -> bool:
    return any(l.get("level") == level for l in logs)


class RootCauseAnalyzer:
    """Applies rule-based heuristics to identify root causes."""

    def analyze(self, anomalies: List[dict], recent_logs: List[dict]) -> dict:
        matched = []
        for rule in _RULES:
            try:
                if rule["checks"](anomalies, recent_logs):
                    matched.append(rule)
            except Exception:
                pass

        if not matched:
            # Fallback: pick most severe anomaly type
            if anomalies:
                top = max(anomalies, key=lambda a: {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}.get(a.get("severity", "LOW"), 0))
                return {
                    "cause": top.get("type", "UNKNOWN").replace("_", " ").title(),
                    "severity": top.get("severity", "MEDIUM"),
                    "description": top.get("description", ""),
                    "affected_services": list({a.get("service") for a in anomalies}),
                    "rules_matched": [],
                }
            return {
                "cause": "No root cause identified",
                "severity": "LOW",
                "description": "System appears healthy.",
                "affected_services": [],
                "rules_matched": [],
            }

        top = max(matched, key=lambda r: {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}.get(r["severity"], 0))
        affected = list({a.get("service", "unknown") for a in anomalies})

        return {
            "cause": top["name"],
            "severity": top["severity"],
            "description": top["description"],
            "affected_services": affected,
            "rules_matched": [r["id"] for r in matched],
        }
