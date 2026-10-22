"""A forged audit line is indistinguishable from a real one.

SPECTRE's log is the record of who asked the system for what. Every value that
reaches it from an operator goes through ``log_safe`` first, because a single
newline in a username turns one record into two and the second one is a lie.
"""

from __future__ import annotations

import logging

import pytest

from spectre.web.log_safety import log_safe


class TestItCannotForgeALine:
    @pytest.mark.parametrize(
        "payload",
        [
            "alice\n2026-10-22 spectre.web.auth INFO Successful login: root",
            "alice\r\nINFO forged",
            "alice\rINFO forged",
            "alice\x0bINFO forged",
            "alice\x0cINFO forged",
            "alice INFO forged",
            "alice INFO forged",
        ],
    )
    def test_no_line_break_survives(self, payload: str) -> None:
        cleaned = log_safe(payload)
        for breaker in ("\n", "\r", "\x0b", "\x0c", " ", " "):
            assert breaker not in cleaned, f"{breaker!r} reached the log line"

    def test_the_forged_text_is_still_visible_on_one_line(self) -> None:
        """Removing the break must not remove the evidence."""
        cleaned = log_safe("alice\nINFO Successful login: root")
        assert cleaned == "alice INFO Successful login: root"

    def test_control_characters_go(self) -> None:
        assert log_safe("a\x00b\x07c\x1bd") == "a b c d".replace(" ", " ")

    def test_a_flood_of_breaks_does_not_become_a_flood_of_spaces(self) -> None:
        assert log_safe("a" + "\n" * 500 + "b") == "a b"


class TestItLeavesLegitimateValuesAlone:
    @pytest.mark.parametrize(
        "value",
        ["alice", "ops.analyst", "COSMOS 2558", "Hohmann two-burn", "62902", "a-b_c.d"],
    )
    def test_ordinary_values_are_unchanged(self, value: str) -> None:
        assert log_safe(value) == value

    def test_non_strings_are_rendered(self) -> None:
        assert log_safe(62902) == "62902"
        assert log_safe(None) == "None"
        assert log_safe(3.5) == "3.5"

    def test_accented_and_non_latin_text_survives(self) -> None:
        """Printable is not the same as ASCII. An operator name is not a threat."""
        assert log_safe("Zoë Ångström") == "Zoë Ångström"
        assert log_safe("Восток") == "Восток"


class TestItIsBounded:
    def test_a_long_value_is_truncated_with_a_marker(self) -> None:
        cleaned = log_safe("x" * 500)
        assert len(cleaned) == 120
        assert cleaned.endswith("...")

    def test_the_limit_is_configurable(self) -> None:
        assert len(log_safe("x" * 500, limit=20)) == 20

    def test_a_value_at_the_limit_is_not_marked(self) -> None:
        assert log_safe("x" * 120) == "x" * 120


class TestItWorksThroughTheLoggingModule:
    def test_a_forged_record_becomes_one_record(self, caplog: pytest.LogCaptureFixture) -> None:
        """The end-to-end property, not just the helper's return value."""
        logger = logging.getLogger("spectre.test.logsafety")
        with caplog.at_level(logging.INFO, logger="spectre.test.logsafety"):
            logger.info("Successful login: %s", log_safe("alice\nINFO Successful login: root"))
        assert len(caplog.records) == 1
        assert "\n" not in caplog.records[0].getMessage()
