"""An element set dated in the future is refused, not read as current (SPC-226, evaluation F-38).

The evaluation named this as speculation, unprobed: elset_age clamped the age of a set dated after now to 0 h, so a
mis-dated set would pass every staleness check. Probed at 602c963 before any change (a LEO and a GEO set dated 48 h
after 12:00 UTC on 13 November 2026, both with good checksums): the acceptance check accepted each, elset_age gave
0.0 h, not stale, labelled "0.0 h", and the decision binding bound each at 0.0 h as current. Confirmed.

Now an epoch more than FUTURE_EPOCH_TOLERANCE after now, five minutes for clock skew (an unsourced judgement in the
lookup register), is refused by the acceptance check on every ingest path and at binding, with a sentence naming the
epoch and how far ahead it is; and elset_age marks such a set as dated in the future, never current, wherever an age
is computed. An epoch within the tolerance still reads as 0 h, as a clock a little ahead would give.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from jinja2 import Environment, FileSystemLoader

from spectre.astro.elset_check import FUTURE_EPOCH_TOLERANCE, check_elset
from spectre.domain.models import RedTrack
from spectre.web.decision_binding import bind_scenario
from spectre.web.elsets import ElsetAge, elset_age, refused
from tests.unit.test_decision_binder import _state
from tests.unit.test_elset_freshness import _tle

_NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
_TEMPLATES = Path(__file__).resolve().parents[2] / "spectre" / "web" / "templates"
_AHEAD = (
    "its epoch, 2026-11-15 12:00 UTC, is 2.0 d after the time it was checked, 2026-11-13 12:00 UTC, more than the "
    "5 minutes allowed for clock skew: a set dated in the future would read as current, so check its epoch and "
    "this server's clock"
)


def test_the_tolerance_is_five_minutes() -> None:
    assert timedelta(minutes=5) == FUTURE_EPOCH_TOLERANCE


class TestTheAge:
    @pytest.mark.parametrize("leo", [True, False], ids=["LEO", "GEO"])
    def test_a_set_48_h_ahead_is_dated_in_the_future_and_never_current(self, leo: bool) -> None:
        age = elset_age(_tle(_NOW + timedelta(hours=48), leo=leo), _NOW)
        assert age is not None
        assert (age.future, age.stale, age.hours) == (True, True, 0.0)
        assert age.ahead_hours == pytest.approx(48.0, abs=1e-6)
        assert age.label == "2.0 d in the future"

    def test_an_hour_ahead_is_labelled_in_hours(self) -> None:
        age = elset_age(_tle(_NOW + timedelta(hours=1), leo=True), _NOW)
        assert age is not None and age.label == "1.0 h in the future"

    @pytest.mark.parametrize("ahead", [timedelta(minutes=4), FUTURE_EPOCH_TOLERANCE], ids=["4 min", "5 min"])
    def test_within_the_tolerance_it_reads_as_now(self, ahead: timedelta) -> None:
        age = elset_age(_tle(_NOW + ahead, leo=True), _NOW)
        assert age is not None
        assert (age.future, age.stale, age.hours, age.ahead_hours, age.label) == (False, False, 0.0, 0.0, "0.0 h")

    def test_just_past_the_tolerance_is_in_the_future(self) -> None:
        age = elset_age(_tle(_NOW + FUTURE_EPOCH_TOLERANCE + timedelta(seconds=1), leo=True), _NOW)
        assert age is not None and age.future is True

    def test_a_set_behind_now_is_aged_as_before(self) -> None:
        age = elset_age(_tle(_NOW - timedelta(hours=10), leo=True), _NOW)
        assert age is not None
        assert (age.future, age.stale, age.ahead_hours, age.label) == (False, False, 0.0, "10.0 h")


class TestTheAcceptanceCheck:
    def test_a_set_dated_ahead_of_the_check_is_refused_naming_its_epoch(self) -> None:
        check = check_elset(_tle(_NOW + timedelta(hours=48)), now=_NOW)
        assert check.failures == (_AHEAD,)

    def test_without_a_clock_the_check_reads_no_date(self) -> None:
        assert check_elset(_tle(_NOW + timedelta(hours=48))).accepted is True

    def test_within_the_tolerance_it_is_accepted(self) -> None:
        assert check_elset(_tle(_NOW + FUTURE_EPOCH_TOLERANCE), now=_NOW).accepted is True

    def test_every_ingest_path_refuses_it_by_the_wall_clock(self) -> None:
        """refused() is the check every ingest path calls; with no time given it reads the wall clock."""
        ahead = datetime.now(UTC) + timedelta(days=3)
        sentence = refused("red track RX", _tle(ahead))
        assert sentence is not None
        assert sentence.startswith(f"The element set for red track RX was refused: its epoch, {ahead:%Y-%m-%d %H:%M}")
        assert sentence.endswith("so check its epoch and this server's clock. It was not stored.")

    def test_refused_takes_the_time_it_is_given(self) -> None:
        assert refused("red track RX", _tle(_NOW + timedelta(hours=48)), now=_NOW) == (
            f"The element set for red track RX was refused: {_AHEAD}. It was not stored."
        )


class TestTheBinding:
    def test_a_set_dated_in_the_future_is_not_bound(self) -> None:
        state = _state([RedTrack("RX", _tle(_NOW + timedelta(hours=48)))])
        outcome = bind_scenario(state, "RX", "", _NOW)
        assert outcome.binding is None
        assert outcome.problem == (
            f"The element set for red track RX was refused: {_AHEAD}. Nothing was bound; add a sound element set "
            "for it."
        )


class TestWhereAgesAreShown:
    """A set held from before 0.42.0, or by a route the check missed, is shown as dated in the future, never as an
    age of 0 h."""

    def _red_card(self, age: ElsetAge) -> str:
        from spectre.web.app import templates as app_templates

        env = Environment(loader=FileSystemLoader(str(_TEMPLATES)), autoescape=True)
        env.filters.update(app_templates.env.filters)
        page = env.get_template("partials/red_orbit_info.html").render(
            name="RX", epoch_str="2026-11-15 12:00", age=age, data_mode="REAL", elset_source="18SDS", lon_deg=1.0,
            inc_deg=0.1, period_min=1436.0, alt_km=35786.0, ecc=0.0002, a_km=42164.0, pair=None,
        )
        return " ".join(page.split())

    def test_the_red_card_says_future_epoch_not_old(self) -> None:
        age = elset_age(_tle(_NOW + timedelta(hours=48)), _NOW)
        assert age is not None
        page = self._red_card(age)
        assert ">2.0 d in the future FUTURE EPOCH</span>" in page
        assert " old" not in page.split("FUTURE EPOCH")[0].rsplit(">", 1)[-1]

    def test_the_red_card_still_says_old_and_stale_for_an_old_set(self) -> None:
        age = elset_age(_tle(_NOW - timedelta(days=13)), _NOW)
        assert age is not None
        assert ">13.0 d old STALE</span>" in self._red_card(age)

    def test_the_sweep_names_a_target_dated_in_the_future_apart_from_the_age_range(self) -> None:
        """V0.42 review: the range took the least hours, so it read "Targets 2.0 d in the future to 13.0 d old"."""
        from spectre.domain.models import ThreatTarget
        from spectre.web.routes.threat import _elset_ages, _FrozenTargets, _SweepBasis

        ahead = ThreatTarget(target_name="AHEAD", target_satno="90002", target_source="hrr", hrr_rank=1)
        old = ThreatTarget(target_name="OLD", target_satno="90003", target_source="hrr", hrr_rank=1)
        fresh = ThreatTarget(target_name="FRESH", target_satno="90004", target_source="hrr", hrr_rank=1)
        basis = _SweepBasis(
            targets=[ahead, old, fresh], manual_tle_by_name={},
            frozen=_FrozenTargets({"90002": _tle(_NOW + timedelta(hours=48), satno=90002),
                                   "90003": _tle(_NOW - timedelta(days=13), satno=90003),
                                   "90004": _tle(_NOW - timedelta(hours=5), satno=90004)}),
            red_regime="GEO", max_dv_m_s=500.0, blue_satnos=frozenset(), now=_NOW,
        )
        ages = _elset_ages(_tle(_NOW - timedelta(hours=2)), basis, _NOW)
        assert ages["future"] == ["AHEAD (dated 2.0 d in the future)"]
        assert (ages["count"], ages["newest"].label, ages["oldest"].label) == (2, "5.0 h", "13.0 d")
        assert ages["stale"] == [f"OLD ({ages['oldest'].regime_line})"]
        page = self._sweep_ages(ages)
        assert "1 FUTURE EPOCH</span>: AHEAD (dated 2.0 d in the future); Targets 5.0 h to 13.0 d old," in page
        assert "in the future to" not in page

    def _sweep_ages(self, ages: dict[str, object]) -> str:
        from jinja2 import ChainableUndefined

        from spectre.web.app import templates as app_templates

        env = Environment(loader=FileSystemLoader(str(_TEMPLATES)), autoescape=True, undefined=ChainableUndefined)
        env.filters.update(app_templates.env.filters)
        env.globals.update(app_templates.env.globals)
        assessment = SimpleNamespace(red_name="RX", target_count=3, entries=[], elapsed_s=1.0)
        page = env.get_template("partials/threat_sweep.html").render(
            elset_ages=ages, assessment=assessment, grouped=[], csrf_token="",
        )
        return " ".join(page.split())

    def test_the_delta_v_band_says_a_set_is_dated_in_the_future_not_0_h_old(self) -> None:
        """V0.42 review: the band's sentence printed age_text of the clamped 0 h for a set dated after now."""
        from spectre.web.routes.threat import _set_age_words

        assert _set_age_words(elset_age(_tle(_NOW + timedelta(hours=48)), _NOW)) == "dated 2.0 d in the future"
        assert _set_age_words(elset_age(_tle(_NOW - timedelta(hours=5)), _NOW)) == "5.0 h old"
        assert _set_age_words(None) == "of unknown age"
