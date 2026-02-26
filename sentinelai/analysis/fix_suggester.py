"""Auto-Fix Suggestion System.

Maps RCA categories to prioritised remediation actions.
Optionally marks actions as "auto-executable" (safe to run without human
approval) vs. "manual" (require explicit approval).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class FixAction:
    """A single remediation action."""

    step: int
    description: str
    auto_executable: bool = False  # True = safe to auto-run in future


@dataclass
class FixSuggestion:
    """Complete fix suggestion for a detected issue."""

    category: str
    service: str
    actions: List[FixAction] = field(default_factory=list)

    def summary(self) -> str:
        lines = [f"Recommended Actions for {self.service} [{self.category.upper()}]:"]
        for action in self.actions:
            auto = " [auto-executable]" if action.auto_executable else ""
            lines.append(f"  {action.step}. {action.description}{auto}")
        return "\n".join(lines)


# ── Fix catalogue ─────────────────────────────────────────────────────────────

_FIX_CATALOGUE: dict[str, List[dict]] = {
    "database": [
        {"description": "Restart the affected service to clear stale DB connections", "auto_executable": True},
        {"description": "Increase database connection pool size (e.g. pool_size=20 → 40)"},
        {"description": "Check DB server CPU / memory and scale vertically if needed"},
        {"description": "Review slow query log and add missing indexes"},
    ],
    "memory": [
        {"description": "Trigger a rolling restart of the service to free leaked memory", "auto_executable": True},
        {"description": "Scale horizontally — add replicas to distribute memory pressure"},
        {"description": "Profile heap usage and fix memory leaks in application code"},
        {"description": "Increase container memory limit if constrained by orchestrator"},
    ],
    "cpu": [
        {"description": "Scale replicas to distribute CPU load", "auto_executable": True},
        {"description": "Identify and throttle CPU-intensive background jobs"},
        {"description": "Review recent deployments for algorithmic regressions"},
    ],
    "network": [
        {"description": "Verify downstream service health and connectivity"},
        {"description": "Check DNS resolution and TLS certificate validity"},
        {"description": "Implement / tune retry logic with exponential back-off"},
        {"description": "Add circuit breaker around the failing downstream call"},
    ],
    "disk": [
        {"description": "Free disk space — archive or delete old log/data files", "auto_executable": True},
        {"description": "Expand persistent volume claim or attach additional storage"},
        {"description": "Review log rotation configuration"},
    ],
    "auth": [
        {"description": "Refresh or rotate expiring tokens/certificates"},
        {"description": "Review RBAC policies for misconfigured permissions"},
        {"description": "Check identity provider availability"},
    ],
    "rate_limit": [
        {"description": "Investigate traffic source — possible DDoS or runaway client"},
        {"description": "Adjust rate-limit thresholds to match legitimate traffic"},
        {"description": "Enable auto-scaling to absorb traffic spikes", "auto_executable": True},
    ],
    "performance": [
        {"description": "Increase service replicas to reduce per-instance load", "auto_executable": True},
        {"description": "Review recent deployments for performance regressions"},
        {"description": "Enable caching for expensive downstream calls"},
    ],
}

_DEFAULT_ACTIONS = [
    {"description": "Collect full logs and escalate to on-call engineer"},
    {"description": "Review recent deployments and roll back if correlated"},
]


class FixSuggester:
    """Suggest remediation actions given an RCA category and service name."""

    def suggest(self, category: str, service: str = "unknown-service") -> FixSuggestion:
        """Return a :class:`FixSuggestion` for the given *category*.

        Parameters
        ----------
        category:
            RCA category string (e.g. "database", "memory", "network").
        service:
            Name of the affected service (used in the summary).
        """
        raw_actions = _FIX_CATALOGUE.get(category.lower(), _DEFAULT_ACTIONS)
        actions = [
            FixAction(
                step=i + 1,
                description=a["description"],
                auto_executable=a.get("auto_executable", False),
            )
            for i, a in enumerate(raw_actions)
        ]
        return FixSuggestion(category=category, service=service, actions=actions)
