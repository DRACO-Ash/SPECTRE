"""A deployment's primary rule, SPECTRE_PRIMARY_RULE (SPC-194, evaluation F-03).

The rule whose pick is the headline recommendation and the panel's default, set for the deployment before use, so it
cannot be chosen after a result is seen. One of minimax, minimin or expected_value; unset, minimax, the cautious rule
(Claude's choice). A value that is none of them is not refused at boot: it is logged as a warning and the primary
rule is minimax, so a typing slip leaves the deployment on the cautious rule and running (Claude's choice).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from spectre.config import settings as settings_module
from spectre.config.settings import DEFAULT_PRIMARY_RULE, PRIMARY_RULES, Settings
from spectre.domain.decision import SelectorStrategy
from spectre.web.decision_record import primary_rule

_ENV = "SPECTRE_PRIMARY_RULE"
_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _fresh_warnings() -> Iterator[None]:
    """Each test sees the warning for a value afresh: it is logged once per value, not on every request."""
    settings_module.primary_rule_of.cache_clear()
    yield
    settings_module.primary_rule_of.cache_clear()


class TestTheSetting:
    def test_unset_it_is_minimax_the_cautious_rule(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(_ENV, raising=False)
        assert Settings().primary_rule == "minimax" == DEFAULT_PRIMARY_RULE

    def test_blank_it_is_minimax(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(_ENV, "  ")
        assert Settings().primary_rule == "minimax"

    @pytest.mark.parametrize("value", ["minimax", "minimin", "expected_value", " Expected_Value ", "MINIMIN"])
    def test_each_rule_is_taken(self, monkeypatch: pytest.MonkeyPatch, value: str) -> None:
        monkeypatch.setenv(_ENV, value)
        assert Settings().primary_rule == value.strip().lower()

    def test_the_rules_are_the_engines_own(self) -> None:
        assert set(PRIMARY_RULES) == {rule.value for rule in SelectorStrategy}

    @pytest.mark.parametrize("value", ["maximin", "expected value", "cautious", "minimax;"])
    def test_an_unknown_value_is_minimax_with_a_warning_naming_it(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, value: str,
    ) -> None:
        monkeypatch.setenv(_ENV, value)
        with caplog.at_level(logging.WARNING, logger="spectre.config.settings"):
            assert Settings().primary_rule == "minimax"
        warned = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warned) == 1
        assert repr(value) in warned[0]
        assert "minimax" in warned[0] and _ENV in warned[0]

    def test_the_warning_is_logged_once_per_value_not_per_request(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setenv(_ENV, "optimistic")
        with caplog.at_level(logging.WARNING, logger="spectre.config.settings"):
            for _ in range(3):
                Settings()
        assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1

    def test_the_web_reads_it_as_a_rule(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(_ENV, "expected_value")
        assert primary_rule() is SelectorStrategy.EXPECTED_VALUE
        monkeypatch.delenv(_ENV)
        assert primary_rule() is SelectorStrategy.MINIMAX

    def test_the_example_environment_documents_it(self) -> None:
        example = _ROOT / ".env.example"
        if not example.exists():
            pytest.skip(".env.example is not in this checkout")
        text = example.read_text(encoding="utf-8")
        assert f"# {_ENV}=" in text
        assert "minimax" in text.split(f"# {_ENV}=")[0].rsplit("\n\n", 1)[-1]
