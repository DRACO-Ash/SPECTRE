"""Custody: timely and actionable information to judge the first two outputs (SPC-018).

The operator's definition (28 October 2026): custody is having timely and
actionable information to determine whether a burn is normal and how the
warning time changed. Each class pins one way of holding or losing it.
"""

from __future__ import annotations

from datetime import UTC, datetime

from spectre.domain.custody import Custody, assess_custody
from spectre.domain.normality import Normality

_NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
_GEO_LIMIT = 72.0


def _held(**kw: object) -> object:
    args: dict[str, object] = {
        "elset_hours": 5.0, "limit_hours": _GEO_LIMIT, "elset_count": 412, "history_days": 190.0,
        "normality": Normality.ROUTINE, "history_problem": "", "truncated_at": None,
    }
    args.update(kw)
    return assess_custody(**args)  # type: ignore[arg-type]


class TestHeld:
    def test_a_fresh_orbit_and_a_history_that_judges_burns(self) -> None:
        status = _held()
        assert status.state is Custody.HELD
        assert status.sentence == (
            "Custody held: its orbit is 5.0 h old (limit 72 h) and 412 element sets "
            "over 190 days judge its burns."
        )

    def test_an_unusual_verdict_is_still_custody_held(self) -> None:
        # Custody is about having the information, not about what it says.
        assert _held(normality=Normality.UNPRECEDENTED).state is Custody.HELD

    def test_no_burns_yet_is_held_when_the_history_is_there(self) -> None:
        # An object that has not manoeuvred is watched, not unknown.
        assert _held(normality=None).state is Custody.HELD


class TestDegraded:
    def test_without_a_history_burns_cannot_be_judged(self) -> None:
        status = _held(normality=None, elset_count=0, history_days=0.0,
                       history_problem="UDL is not connected, so no element-set history is held.")
        assert status.state is Custody.DEGRADED
        assert "whether its burns are normal cannot be judged" in status.sentence
        assert "UDL is not connected" in status.sentence

    def test_too_little_history_is_degraded(self) -> None:
        status = _held(normality=Normality.NOT_ENOUGH_HISTORY, elset_count=40, history_days=12.0)
        assert status.state is Custody.DEGRADED
        assert "too little history" in status.sentence

    def test_a_truncated_history_is_degraded(self) -> None:
        status = _held(truncated_at=datetime(2026, 9, 1, tzinfo=UTC))
        assert status.state is Custody.DEGRADED
        assert "missing after 2026-09-01" in status.sentence


class TestLost:
    def test_a_stale_orbit_loses_custody_whatever_the_history(self) -> None:
        status = _held(elset_hours=13 * 24.0)
        assert status.state is Custody.LOST
        assert status.sentence == (
            "Custody lost: its newest element set is 13.0 d old against a 72 h limit, "
            "so its warning time is out of date and a burn since then would not be seen."
        )

    def test_no_readable_orbit_loses_custody(self) -> None:
        status = _held(elset_hours=None)
        assert status.state is Custody.LOST
        assert "no element set with a readable epoch" in status.sentence

    def test_the_limit_itself_is_still_held(self) -> None:
        assert _held(elset_hours=_GEO_LIMIT).state is Custody.HELD


class TestItSaysWhatItRestsOn:
    def test_the_basis_names_the_operator_definition(self) -> None:
        assert "timely and actionable" in _held().basis
