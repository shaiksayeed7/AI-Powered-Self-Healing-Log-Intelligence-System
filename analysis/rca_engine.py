"""
Root Cause Analysis (RCA) Engine – rule-based pattern matching.

Each :class:`Rule` captures a named pattern defined by a set of signals
that, when all present, point to a probable root cause.

The engine is intentionally kept simple so it can be extended later with
LLM-based reasoning without changing the public interface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ingestion.log_parser import LogEntry


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class RCAResult:
    probable_cause: Optional[str]
    matched_rule: Optional[str]
    signals: list[str]
    confidence: float  # 0–1

    def to_dict(self) -> dict:
        return {
            "probable_cause": self.probable_cause,
            "matched_rule": self.matched_rule,
            "signals": self.signals,
            "confidence": round(self.confidence, 2),
        }


# ---------------------------------------------------------------------------
# Rule definition
# ---------------------------------------------------------------------------

@dataclass
class Rule:
    name: str
    description: str
    # Each signal is a callable that takes a list of recent LogEntry objects
    # and returns True when it detects its pattern.
    signals: list
    probable_cause: str
    confidence: float = 0.80


# ---------------------------------------------------------------------------
# Built-in rules
# ---------------------------------------------------------------------------

def _high_error_rate(entries: list[LogEntry]) -> bool:
    if not entries:
        return False
    errors = sum(1 for e in entries if e.level in ("ERROR", "CRITICAL"))
    return errors / len(entries) > 0.3


def _db_timeout(entries: list[LogEntry]) -> bool:
    keywords = {"db_connection_timeout", "db_timeout", "connection_timeout",
                "connection pool", "too many connections"}
    for e in entries:
        msg = e.message.lower()
        if any(kw in msg for kw in keywords):
            return True
        if e.error_type and "timeout" in e.error_type.lower():
            return True
    return False


def _connection_pool_exhaustion(entries: list[LogEntry]) -> bool:
    keywords = {"connection pool", "pool exhausted", "no connections available",
                "pool_exhausted", "max_connections"}
    for e in entries:
        msg = e.message.lower()
        if any(kw in msg for kw in keywords):
            return True
    return False


def _high_latency(entries: list[LogEntry]) -> bool:
    latencies = [e.latency_ms for e in entries if e.latency_ms is not None]
    if not latencies:
        return False
    return sum(latencies) / len(latencies) > 500


def _memory_error(entries: list[LogEntry]) -> bool:
    keywords = {"out of memory", "oom", "memory_error", "memoryerror",
                "heap space", "gc overhead"}
    for e in entries:
        msg = e.message.lower()
        if any(kw in msg for kw in keywords):
            return True
    return False


def _service_unavailable(entries: list[LogEntry]) -> bool:
    keywords = {"503", "service unavailable", "upstream connect error",
                "connection refused", "no route to host"}
    for e in entries:
        msg = e.message.lower()
        if any(kw in msg for kw in keywords):
            return True
    return False


def _disk_full(entries: list[LogEntry]) -> bool:
    keywords = {"no space left", "disk full", "disk_full", "enospc",
                "storage quota exceeded"}
    for e in entries:
        if any(kw in e.message.lower() for kw in keywords):
            return True
    return False


_RULES: list[Rule] = [
    Rule(
        name="DB_OVERLOAD",
        description="Database overload indicated by timeouts and pool exhaustion",
        signals=[_high_error_rate, _db_timeout, _connection_pool_exhaustion],
        probable_cause="Database overload – connection pool exhausted and DB timeouts detected",
        confidence=0.90,
    ),
    Rule(
        name="HIGH_LATENCY_DB",
        description="High latency combined with DB timeouts",
        signals=[_high_latency, _db_timeout],
        probable_cause="Slow database queries causing high end-to-end latency",
        confidence=0.80,
    ),
    Rule(
        name="MEMORY_SATURATION",
        description="Out-of-memory conditions",
        signals=[_memory_error, _high_error_rate],
        probable_cause="Memory saturation – process approaching OOM limit",
        confidence=0.85,
    ),
    Rule(
        name="UPSTREAM_UNAVAILABLE",
        description="Upstream / dependent service is unreachable",
        signals=[_service_unavailable, _high_error_rate],
        probable_cause="Upstream dependency is unavailable or overloaded",
        confidence=0.80,
    ),
    Rule(
        name="DISK_FULL",
        description="Disk space exhausted",
        signals=[_disk_full],
        probable_cause="Disk full – storage exhausted on the host",
        confidence=0.95,
    ),
    Rule(
        name="GENERAL_ERROR_SPIKE",
        description="General error rate spike without clear sub-cause",
        signals=[_high_error_rate],
        probable_cause="Unexplained error spike – manual investigation needed",
        confidence=0.50,
    ),
]


# ---------------------------------------------------------------------------
# RCA Engine
# ---------------------------------------------------------------------------

class RCAEngine:
    """
    Rule-based root cause analysis engine.

    Feed it a window of recent :class:`~ingestion.log_parser.LogEntry`
    objects via :meth:`analyse` and receive an :class:`RCAResult`.
    """

    def __init__(self, rules: Optional[list[Rule]] = None) -> None:
        self._rules = rules if rules is not None else _RULES

    def analyse(self, entries: list[LogEntry]) -> RCAResult:
        """
        Evaluate all rules against *entries* and return the best matching
        :class:`RCAResult`.
        """
        best: Optional[Rule] = None
        best_matched: int = 0
        best_signals: list[str] = []

        for rule in self._rules:
            triggered = [fn for fn in rule.signals if fn(entries)]
            if len(triggered) == len(rule.signals) and len(triggered) > best_matched:
                best = rule
                best_matched = len(triggered)
                best_signals = [fn.__name__ for fn in triggered]

        if best:
            return RCAResult(
                probable_cause=best.probable_cause,
                matched_rule=best.name,
                signals=best_signals,
                confidence=best.confidence,
            )

        return RCAResult(
            probable_cause=None,
            matched_rule=None,
            signals=[],
            confidence=0.0,
        )
