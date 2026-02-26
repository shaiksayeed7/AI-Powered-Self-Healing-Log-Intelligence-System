"""Tests for the Fix Suggester module."""

from datetime import datetime

import pytest

from analysis.fix_suggester import FixAction, FixSuggester, FixSuggestion
from analysis.rca_engine import RCAResult


def _rca(rule="DB_OVERLOAD", cause="DB overload", confidence=0.90):
    return RCAResult(
        probable_cause=cause,
        matched_rule=rule,
        signals=["_high_error_rate", "_db_timeout"],
        confidence=confidence,
    )


class TestFixSuggester:
    def setup_method(self):
        self.suggester = FixSuggester()

    def test_returns_fix_suggestion(self):
        rca = _rca()
        fix = self.suggester.suggest(rca, "payment-api")
        assert isinstance(fix, FixSuggestion)

    def test_fix_has_actions(self):
        fix = self.suggester.suggest(_rca("DB_OVERLOAD"), "payment-api")
        assert len(fix.actions) > 0

    def test_actions_are_fix_action_instances(self):
        fix = self.suggester.suggest(_rca("DB_OVERLOAD"), "payment-api")
        for action in fix.actions:
            assert isinstance(action, FixAction)
            assert action.step >= 1

    def test_steps_are_sequential(self):
        fix = self.suggester.suggest(_rca("DB_OVERLOAD"), "payment-api")
        for i, action in enumerate(fix.actions):
            assert action.step == i + 1

    def test_service_name_substituted_in_command(self):
        fix = self.suggester.suggest(_rca("MEMORY_SATURATION"), "my-service")
        commands = [a.command for a in fix.actions if a.command]
        for cmd in commands:
            assert "my-service" in cmd

    def test_unknown_rule_returns_default_fixes(self):
        rca = RCAResult(
            probable_cause="Unknown",
            matched_rule="NONEXISTENT_RULE",
            signals=[],
            confidence=0.5,
        )
        fix = self.suggester.suggest(rca, "svc")
        assert len(fix.actions) > 0

    def test_no_match_returns_default(self):
        rca = RCAResult(
            probable_cause=None,
            matched_rule=None,
            signals=[],
            confidence=0.0,
        )
        fix = self.suggester.suggest(rca, "svc")
        assert len(fix.actions) > 0

    def test_to_dict(self):
        fix = self.suggester.suggest(_rca("DISK_FULL"), "storage-svc")
        d = fix.to_dict()
        assert "service" in d
        assert "actions" in d
        assert isinstance(d["actions"], list)

    def test_disk_full_fixes(self):
        fix = self.suggester.suggest(_rca("DISK_FULL"), "storage-svc")
        descriptions = [a.description.lower() for a in fix.actions]
        assert any("log" in d or "disk" in d or "storage" in d for d in descriptions)

    def test_upstream_unavailable_has_auto_executable(self):
        fix = self.suggester.suggest(_rca("UPSTREAM_UNAVAILABLE"), "api-gw")
        auto = [a for a in fix.actions if a.auto_executable]
        assert len(auto) >= 1
