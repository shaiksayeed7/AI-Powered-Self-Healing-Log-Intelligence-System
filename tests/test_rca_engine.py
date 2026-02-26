"""Tests for the Root Cause Analysis Engine and Fix Suggester."""

import pytest

from sentinelai.analysis.rca_engine import RCAEngine
from sentinelai.analysis.fix_suggester import FixSuggester


class TestRCAEngine:
    def setup_method(self):
        self.engine = RCAEngine()

    def test_db_timeout_identified(self):
        result = self.engine.analyse(["DB_CONNECTION_TIMEOUT"])
        assert result is not None
        assert result.category == "database"
        assert "DB_CONNECTION_TIMEOUT" in result.matched_patterns

    def test_connection_pool_exhausted(self):
        result = self.engine.analyse(["CONNECTION_POOL_EXHAUSTED"])
        assert result is not None
        assert result.category == "database"

    def test_memory_error(self):
        result = self.engine.analyse(["OUT_OF_MEMORY"])
        assert result is not None
        assert result.category == "memory"

    def test_network_error(self):
        result = self.engine.analyse(["NETWORK_TIMEOUT"])
        assert result is not None
        assert result.category == "network"

    def test_auth_failure(self):
        result = self.engine.analyse(["AUTH_FAILURE"])
        assert result is not None
        assert result.category == "auth"

    def test_unknown_codes_return_none(self):
        result = self.engine.analyse(["TOTALLY_UNKNOWN_CODE_XYZ"])
        assert result is None

    def test_message_fallback(self):
        result = self.engine.analyse([], messages=["Connection to database timed out DB_CONNECTION_TIMEOUT"])
        assert result is not None
        assert result.category == "database"

    def test_multiple_codes_first_rule_wins(self):
        result = self.engine.analyse(["DB_CONNECTION_TIMEOUT", "OUT_OF_MEMORY"])
        assert result is not None
        # database rule has higher priority
        assert result.category == "database"

    def test_summarise_returns_string(self):
        result = self.engine.analyse(["NETWORK_TIMEOUT"])
        assert result is not None
        summary = self.engine.summarise(result)
        assert isinstance(summary, str)
        assert "NETWORK" in summary.upper()


class TestFixSuggester:
    def setup_method(self):
        self.suggester = FixSuggester()

    def test_database_suggestions(self):
        fix = self.suggester.suggest("database", "payment-api")
        assert fix.service == "payment-api"
        assert len(fix.actions) > 0
        assert any("DB" in a.description.upper() or "pool" in a.description.lower()
                   or "connection" in a.description.lower()
                   for a in fix.actions)

    def test_memory_suggestions(self):
        fix = self.suggester.suggest("memory", "worker")
        assert len(fix.actions) > 0

    def test_unknown_category_returns_default(self):
        fix = self.suggester.suggest("unknown_category_xyz", "svc")
        assert len(fix.actions) > 0

    def test_steps_are_numbered(self):
        fix = self.suggester.suggest("network", "svc")
        for i, action in enumerate(fix.actions, start=1):
            assert action.step == i

    def test_summary_contains_service(self):
        fix = self.suggester.suggest("database", "payment-api")
        summary = fix.summary()
        assert "payment-api" in summary
