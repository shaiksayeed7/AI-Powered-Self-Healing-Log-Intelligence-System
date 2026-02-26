"""Root Cause Analysis (RCA) Engine.

Rule-based engine that maps observed error patterns to probable root causes.

Rules are evaluated in priority order.  The first matching rule wins.
Each rule specifies:
- ``conditions``: set of error-code / pattern keywords to look for
- ``cause``: human-readable probable cause
- ``category``: technical category (database, network, memory, …)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Set


@dataclass
class RCAResult:
    """Result of root-cause analysis."""

    probable_cause: str
    category: str
    matched_patterns: List[str]
    confidence: str  # "high" | "medium" | "low"


# ── Rule definitions ──────────────────────────────────────────────────────────

@dataclass
class _Rule:
    keywords: Set[str]      # any match triggers the rule
    cause: str
    category: str
    confidence: str = "high"


_RULES: List[_Rule] = [
    _Rule(
        keywords={"DB_CONNECTION_TIMEOUT", "CONNECTION_POOL_EXHAUSTED", "POOL_EXHAUSTION",
                  "DB_TIMEOUT", "DATABASE_TIMEOUT"},
        cause="Database overload or connection pool exhaustion",
        category="database",
    ),
    _Rule(
        keywords={"HTTP_500", "INTERNAL_SERVER_ERROR", "DB_QUERY_FAILED",
                  "DB_CONNECTION", "SQL_ERROR"},
        cause="Backend service error — likely database or downstream dependency failure",
        category="database",
        confidence="medium",
    ),
    _Rule(
        keywords={"MEMORY_SATURATION", "OUT_OF_MEMORY", "OOM", "HEAP_OVERFLOW",
                  "MEMORY_LEAK"},
        cause="Memory saturation / out-of-memory condition",
        category="memory",
    ),
    _Rule(
        keywords={"CPU_THROTTLE", "CPU_LIMIT", "HIGH_CPU", "CPU_SATURATION"},
        cause="CPU throttling / high CPU load",
        category="cpu",
    ),
    _Rule(
        keywords={"NETWORK_TIMEOUT", "CONNECTION_REFUSED", "DNS_FAILURE",
                  "TLS_HANDSHAKE_FAILED", "NETWORK_ERROR"},
        cause="Network connectivity issue or downstream service unreachable",
        category="network",
    ),
    _Rule(
        keywords={"DISK_FULL", "NO_SPACE_LEFT", "DISK_IO_ERROR", "WRITE_FAILED"},
        cause="Disk capacity or I/O issue",
        category="disk",
    ),
    _Rule(
        keywords={"AUTH_FAILURE", "UNAUTHORIZED", "FORBIDDEN", "JWT_EXPIRED",
                  "TOKEN_INVALID"},
        cause="Authentication / authorisation failure",
        category="auth",
    ),
    _Rule(
        keywords={"RATE_LIMIT", "TOO_MANY_REQUESTS", "THROTTLED"},
        cause="Rate limiting triggered — traffic spike or misconfigured limits",
        category="rate_limit",
    ),
    _Rule(
        keywords={"TIMEOUT", "REQUEST_TIMEOUT", "DEADLINE_EXCEEDED"},
        cause="Request timeout — service may be overloaded or slow downstream",
        category="performance",
        confidence="medium",
    ),
]


class RCAEngine:
    """Evaluate a set of error codes and log patterns against known rules."""

    def analyse(
        self,
        error_codes: List[str],
        messages: Optional[List[str]] = None,
    ) -> Optional[RCAResult]:
        """Return the best-matching :class:`RCAResult` or *None*.

        Parameters
        ----------
        error_codes:
            List of error code strings extracted from log records.
        log_messages:
            Optional list of raw log message strings for fallback keyword matching.
        """
        # Build normalised token set
        tokens: Set[str] = set()
        for code in error_codes:
            tokens.add(code.upper().strip())

        if messages:
            for msg in messages:
                for word in msg.upper().split():
                    tokens.add(word.strip(".,;:()[]{}"))

        for rule in _RULES:
            matched = list(rule.keywords & tokens)
            if matched:
                return RCAResult(
                    probable_cause=rule.cause,
                    category=rule.category,
                    matched_patterns=matched,
                    confidence=rule.confidence,
                )

        return None

    def summarise(self, result: RCAResult) -> str:
        """Return a human-readable summary of the RCA result."""
        patterns = ", ".join(result.matched_patterns)
        return (
            f"Probable Cause [{result.category.upper()}]: {result.probable_cause}\n"
            f"Matched patterns: {patterns}\n"
            f"Confidence: {result.confidence}"
        )
