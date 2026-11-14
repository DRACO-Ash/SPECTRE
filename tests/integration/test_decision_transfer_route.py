"""A scenario opened from the sweep carries every burn of the transfer through Evaluate (SPC-184).

The panel opened from an entry whose transfer has several burns lists every burn in words and posts the later
burns in a hidden field beside the first burn's fixed time. Evaluate reads them back, each at its own UTC time with
its own prograde, normal and radial parts in m/s, and carries them on the row's hypothesis as one action with one P.
A later burn that cannot be read, is out of time order, comes after the horizon or rides on a row with no fixed
burn time is refused beside the form, never as a server error and never with exception text. Each route clock is
fixed and no sampled job runs.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from spectre.domain.decision_transfer import TransferBurn
from spectre.domain.models import SweepBurn
from spectre.web.decision_job import DecisionJob
from spectre.web.routes import decision as decision_routes
from tests.integration.test_decision_from_sweep_route import (  # noqa: F401 - held and captured are fixtures
    _DEPART,
    _NOW,
    _entry,
    _evaluate,
    _field,
    _open,
    _refusal,
    _scenario,
    _sweep_form,
    _text,
    captured,
    held,
)

_MID = _NOW + timedelta(hours=3)
_ARRIVE = _NOW + timedelta(hours=6)
_THEN = f"{_MID.isoformat()} -12.5 0.0 3.0;{_ARRIVE.isoformat()} 0.0 0.0 -2.0"


def _transfer_entry() -> Any:
    entry = _entry()
    entry.transfer_m_s = (
        SweepBurn(_DEPART, 30.0, 40.0, 0.0), SweepBurn(_MID, -12.5, 0.0, 3.0), SweepBurn(_ARRIVE, 0.0, 0.0, -2.0),
    )
    # Priced at the sum of its burns, as a sweep solution that lists every burn is.
    entry.delta_v_m_s = 50.0 + (12.5**2 + 3.0**2) ** 0.5 + 2.0
    return entry


class TestThePanel:
    def test_it_lists_every_burn_and_carries_the_later_ones(
        self, client: Any, auth_cookie: str, held: Any,  # noqa: F811
    ) -> None:
        held.last_threat_assessment.entries = [_transfer_entry()]
        page = _open(client, auth_cookie)
        text = _text(page)
        assert "This row carries 3 burns of one transfer as one action, listed in time order:" in text
        assert "Burn 2 at 12:00 UTC on 4 Nov, 12.9 m/s (prograde -12.5, normal 0.0 and radial 3.0 m/s)." in text
        assert [f'value="{_THEN}"' in f for f in _field(page, "hyp_then")] == [True]


class TestEvaluate:
    def test_the_later_burns_ride_on_the_rows_hypothesis(
        self, client: Any, auth_cookie: str, held: Any, captured: list[DecisionJob],  # noqa: F811
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(decision_routes, "needs_a_run", lambda _scenario: True)
        resp = _evaluate(client, auth_cookie, _sweep_form(hyp_then=[_THEN]))
        assert "error-msg" not in resp.text
        carried = _scenario(captured).adversary_actions[0].hypothesis
        assert carried is not None
        assert carried.hypothesis.epoch_utc == _DEPART
        assert carried.then == (TransferBurn(_MID, -12.5, 0.0, 3.0), TransferBurn(_ARRIVE, 0.0, 0.0, -2.0))

    def test_a_blank_column_carries_one_burn_as_before(
        self, client: Any, auth_cookie: str, held: Any, captured: list[DecisionJob],  # noqa: F811
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(decision_routes, "needs_a_run", lambda _scenario: True)
        resp = _evaluate(client, auth_cookie, _sweep_form(hyp_then=[""]))
        assert "error-msg" not in resp.text
        carried = _scenario(captured).adversary_actions[0].hypothesis
        assert carried is not None and carried.then == ()

    @pytest.mark.parametrize(("columns", "message"), [
        ({"hyp_then": ["soon"]}, "The transfer's later burns in row 1 cannot be read; reload the panel."),
        ({"hyp_then": [f"{_MID.isoformat()} 1 2"]},
         "The transfer's later burns in row 1 cannot be read; reload the panel."),
        ({"hyp_then": ["2026-11-04T12:00:00 1 2 3"]},
         "The transfer's later burns in row 1 cannot be read; reload the panel."),
        ({"hyp_then": [f"{_MID.isoformat()} nan 0 0"]},
         "The transfer's later burns in row 1 cannot be read; reload the panel."),
        ({"hyp_then": [f"{_MID.isoformat()} 2000 0 0"]},
         "Burn 2 of the transfer in row 1 is 2,000 m/s, over the 1,000 m/s a burn may be. Set the row's archetype "
         "to None to keep it a lookup, or open a cheaper entry from the sweep."),
        # The limit is on the burn's size, as burn 1's is, not on each part.
        ({"hyp_then": [f"{_MID.isoformat()} 800 0 0;{_ARRIVE.isoformat()} 800 0 800"]},
         "Burn 3 of the transfer in row 1 is 1,131 m/s, over the 1,000 m/s a burn may be."),
        ({"hyp_then": [f"{_MID.isoformat()} fast 0 0"]},
         "The transfer's later burns in row 1 cannot be read; reload the panel."),
        ({"hyp_then": [f"{(_DEPART - timedelta(minutes=1)).isoformat()} 1 0 0"]},
         "The transfer's later burns in row 1 are not in time order after its first; reload the panel."),
        ({"hyp_then": [f"{(_NOW + timedelta(hours=8)).isoformat()} 1 0 0"]},
         "Burn 2 of the transfer in row 1, at 17:00 UTC on 4 Nov, is after the horizon. Lengthen the horizon to "
         "cover it."),
        ({"hyp_then": [";".join(f"{(_MID + timedelta(minutes=k)).isoformat()} 1 0 0" for k in range(8))]},
         "The transfer in row 1 carries more than 8 burns; reload the panel."),
        ({"hyp_then": [_THEN], "hyp_burn_at": [""], "hyp_burn_h": ["1"]},
         "The transfer's later burns in row 1 need its first burn's fixed time; reload the panel."),
        ({"hyp_then": [_THEN, ""]}, "The hypothesis fields do not match the adversary rows; reload the panel."),
    ], ids=["unread", "three-parts", "no-offset", "nan", "too-big", "too-big-in-size", "not-a-number", "before-first", "after-horizon", "too-many",
            "no-fixed-time", "misaligned"])
    def test_a_later_burn_that_cannot_be_used_is_refused(
        self, client: Any, auth_cookie: str, held: Any, columns: dict[str, list[str]], message: str,  # noqa: F811
    ) -> None:
        assert message in _refusal(client, auth_cookie, _sweep_form(**columns))

    def test_a_detected_row_carries_no_transfer(
        self, client: Any, auth_cookie: str, held: Any,  # noqa: F811
    ) -> None:
        at = _NOW - timedelta(hours=6)
        form = _sweep_form(hyp_archetype=["repositioning"], hyp_burn_at=[at.isoformat()], hyp_detected=["1"],
                           hyp_then=[_THEN])
        assert ("The transfer's later burns in row 1 need its first burn's fixed time; reload the panel."
                in _refusal(client, auth_cookie, form))
