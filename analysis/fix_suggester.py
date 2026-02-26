"""
Auto-Fix Suggestion System – maps root causes to actionable remediation steps.

Given an :class:`~analysis.rca_engine.RCAResult` (and optionally a raw cause
string) the engine returns an ordered list of recommended actions plus an
optional *auto-executable* flag that signals whether the action is safe to run
automatically.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from analysis.rca_engine import RCAResult


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class FixAction:
    step: int
    description: str
    command: Optional[str] = None   # shell command if auto-executable
    auto_executable: bool = False   # requires human approval by default


@dataclass
class FixSuggestion:
    service: str
    rule_name: Optional[str]
    probable_cause: Optional[str]
    actions: list[FixAction] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "service": self.service,
            "rule_name": self.rule_name,
            "probable_cause": self.probable_cause,
            "actions": [
                {
                    "step": a.step,
                    "description": a.description,
                    "command": a.command,
                    "auto_executable": a.auto_executable,
                }
                for a in self.actions
            ],
        }


# ---------------------------------------------------------------------------
# Fix catalogue – maps rule names to fix templates
# ---------------------------------------------------------------------------

_FIX_CATALOGUE: dict[str, list[dict]] = {
    "DB_OVERLOAD": [
        {
            "description": "Increase DB connection pool size (e.g. pool_size → 20)",
            "command": None,
            "auto_executable": False,
        },
        {
            "description": "Restart the affected service to release stale connections",
            "command": "systemctl restart {service}",
            "auto_executable": False,
        },
        {
            "description": "Scale service replicas to distribute DB load (e.g. replicas 3 → 6)",
            "command": None,
            "auto_executable": False,
        },
        {
            "description": "Investigate long-running queries and add indexes",
            "command": None,
            "auto_executable": False,
        },
    ],
    "HIGH_LATENCY_DB": [
        {
            "description": "Enable query result caching (Redis/Memcached)",
            "command": None,
            "auto_executable": False,
        },
        {
            "description": "Review and optimise slow SQL queries",
            "command": None,
            "auto_executable": False,
        },
        {
            "description": "Add a read replica to offload SELECT traffic",
            "command": None,
            "auto_executable": False,
        },
    ],
    "MEMORY_SATURATION": [
        {
            "description": "Restart the service to reclaim leaked memory",
            "command": "systemctl restart {service}",
            "auto_executable": False,
        },
        {
            "description": "Increase container/pod memory limit",
            "command": None,
            "auto_executable": False,
        },
        {
            "description": "Profile for memory leaks (use memory_profiler or heapdump)",
            "command": None,
            "auto_executable": False,
        },
    ],
    "UPSTREAM_UNAVAILABLE": [
        {
            "description": "Check upstream service health endpoint",
            "command": "curl -sf http://{service}/health",
            "auto_executable": True,
        },
        {
            "description": "Enable circuit breaker / retry with exponential back-off",
            "command": None,
            "auto_executable": False,
        },
        {
            "description": "Scale up upstream service replicas",
            "command": None,
            "auto_executable": False,
        },
    ],
    "DISK_FULL": [
        {
            "description": "Remove old log files / rotate logs immediately",
            "command": "find /var/log -name '*.log' -mtime +7 -delete",
            "auto_executable": False,
        },
        {
            "description": "Expand the disk volume or mount a larger storage device",
            "command": None,
            "auto_executable": False,
        },
        {
            "description": "Move large data files to object storage (S3/GCS)",
            "command": None,
            "auto_executable": False,
        },
    ],
    "GENERAL_ERROR_SPIKE": [
        {
            "description": "Examine recent deployments for regressions",
            "command": None,
            "auto_executable": False,
        },
        {
            "description": "Check resource utilisation (CPU, memory, network)",
            "command": None,
            "auto_executable": False,
        },
        {
            "description": "Review error logs for common patterns",
            "command": None,
            "auto_executable": False,
        },
    ],
}

_DEFAULT_FIXES: list[dict] = [
    {
        "description": "Review recent changes and roll back if needed",
        "command": None,
        "auto_executable": False,
    },
    {
        "description": "Check system resource utilisation",
        "command": None,
        "auto_executable": False,
    },
]


# ---------------------------------------------------------------------------
# Fix Suggester
# ---------------------------------------------------------------------------

class FixSuggester:
    """
    Generate remediation suggestions from an :class:`~analysis.rca_engine.RCAResult`.
    """

    def suggest(self, rca: RCAResult, service: str) -> FixSuggestion:
        """Return a :class:`FixSuggestion` for the given RCA result."""
        templates = _FIX_CATALOGUE.get(rca.matched_rule or "", _DEFAULT_FIXES)
        actions = [
            FixAction(
                step=i + 1,
                description=t["description"].replace("{service}", service),
                command=(
                    t["command"].replace("{service}", service)
                    if t["command"]
                    else None
                ),
                auto_executable=t["auto_executable"],
            )
            for i, t in enumerate(templates)
        ]
        return FixSuggestion(
            service=service,
            rule_name=rca.matched_rule,
            probable_cause=rca.probable_cause,
            actions=actions,
        )
