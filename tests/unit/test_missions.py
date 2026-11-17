"""The Orbital Watch mission engine (SPC-248): the schema checked at load, answers, stars, the clock and the texts.

The training audit of 16 November 2026 found instructions naming controls that do not exist, briefings whose figures
their own element sets contradict, and objectives that scored without the operator doing anything. A mission file
that names an unknown role, quantity, check or placeholder, types a figure, or names a control its words do not, must
fail to load, so the test suite finds it, not an operator.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import yaml

from spectre.training import missions
from spectre.training.missions import MissionError, load_campaign, parse
from spectre.training.quantities import Bound


def _raw() -> dict[str, Any]:
    with open(missions._CONFIG_PATH, encoding="utf-8") as fh:
        return dict(yaml.safe_load(fh))


def _broken(change: Any) -> str:
    raw = copy.deepcopy(_raw())
    change(raw["missions"][0])
    with pytest.raises(MissionError) as caught:
        parse(raw)
    return str(caught.value)


class TestTheCampaignLoads:
    def test_chapters_one_and_two_hold_the_seven_missions(self) -> None:
        campaign = load_campaign()
        assert [c.id for c in campaign.chapters] == ["first_watch", "shadows"]
        assert [m.id for m in campaign.in_chapter("first_watch")] == [
            "know_your_asset", "who_is_near", "the_sweep", "read_a_threat"]
        assert [m.id for m in campaign.in_chapter("shadows")] == ["the_tug", "the_inspector", "the_listener"]

    def test_every_role_is_a_real_watchlist_object_or_the_nearest_of_one(self) -> None:
        for mission in load_campaign().missions:
            for role in mission.roles:
                assert role.satno in missions.watchlist() or role.nearest_to

    def test_no_objective_is_self_certified(self) -> None:
        for mission in load_campaign().missions:
            for o in mission.objectives:
                assert (o.kind == "condition" and o.check) or o.quantity or o.options_from


class TestLoadingFailsLoudly:
    def test_an_unknown_role_in_a_quantity(self) -> None:
        assert "unknown role 'ghost'" in _broken(lambda m: m["quantities"]["lon"]["args"].update(role="ghost"))

    def test_an_unknown_quantity_function(self) -> None:
        assert "unknown function 'guess'" in _broken(lambda m: m["quantities"]["lon"].update(fn="guess"))

    def test_an_unknown_check_type(self) -> None:
        def change(m: dict[str, Any]) -> None:
            m["objectives"][0] = {"id": "x", "kind": "condition", "text": "Do it.", "points": 10,
                                  "check": {"type": "ticked_a_box"}}
        assert "unknown check type 'ticked_a_box'" in _broken(change)

    def test_an_unknown_placeholder(self) -> None:
        assert "unknown placeholder {nowhere}" in _broken(lambda m: m.update(alert="Look at {nowhere}."))

    def test_a_figure_typed_into_the_text(self) -> None:
        assert "a figure is typed" in _broken(lambda m: m.update(alert="{asset} sits at 75.3 degrees east."))

    def test_a_name_with_a_digit_in_it_is_not_a_figure(self) -> None:
        raw = copy.deepcopy(_raw())
        raw["missions"][0]["brief"] = ["SGP4 propagates the set."]
        assert parse(raw).missions[0].brief == ("SGP4 propagates the set.",)

    def test_a_control_the_words_do_not_name(self) -> None:
        assert "names control 'Quick-Add Blue'" in _broken(
            lambda m: m["objectives"][0].update(controls=["Quick-Add Blue"]))

    def test_an_alert_over_fifteen_words(self) -> None:
        assert "over 15 words" in _broken(lambda m: m.update(alert="word " * 16))

    def test_a_brief_line_over_twenty_five_words(self) -> None:
        assert "over 25 words" in _broken(lambda m: m.update(brief=["word " * 26]))

    def test_a_catalogue_number_off_the_watchlist(self) -> None:
        assert "99001 is not a catalogue number" in _broken(lambda m: m["roles"]["asset"].update(satno="99001"))

    def test_a_blue_object_bound_as_red(self) -> None:
        assert "is not red on the watchlist" in _broken(lambda m: m["roles"]["asset"].update(side="red"))

    def test_an_answer_against_an_options_quantity(self) -> None:
        assert "is not a number" in _broken(lambda m: m["objectives"][0].update(quantity="regime"))

    def test_a_choice_from_a_number(self) -> None:
        assert "is not an options quantity" in _broken(lambda m: m["objectives"][2].update(options_from="lon"))

    def test_an_inject_at_an_unreadable_time(self) -> None:
        assert "at must be start" in _broken(
            lambda m: m.update(inject={"role": "asset", "burn_m_s": [0, 0, 1], "at": "noon"}))

    def test_an_inject_after_the_start_until_a_later_burn_is_handled(self) -> None:
        """N9: a later burn needs the unburned set until then, which no console tool can take beside the burned one."""
        assert "at must be start" in _broken(
            lambda m: m.update(inject={"role": "asset", "burn_m_s": [0, 0, 1], "at": "start+30m"}))

    def test_a_screening_question_before_its_screening(self) -> None:
        """B2: a question read from the operator's own screening must come after the condition that they ran it."""
        raw = copy.deepcopy(_raw())
        who = next(m for m in raw["missions"] if m["id"] == "who_is_near")
        who["objectives"] = [who["objectives"][1], who["objectives"][0], who["objectives"][2]]
        with pytest.raises(MissionError, match="a screening_run of it must come first"):
            parse(raw)

    def test_a_screened_figure_in_a_text(self) -> None:
        raw = copy.deepcopy(_raw())
        next(m for m in raw["missions"] if m["id"] == "who_is_near")["alert"] = "{candidates} could reach {asset}."
        with pytest.raises(MissionError, match="unknown placeholder"):
            parse(raw)


class TestAnswers:
    @pytest.mark.parametrize(("given", "unit", "value"), [
        ("79.72° E", "deg", 79.72), ("0.50° W", "deg", -0.5), ("-12.5", "deg", -12.5), ("14", "count", 14.0),
        ("14 objects", "count", 14.0), ("1435.93 min", "min", 1435.93), ("16.6 km", "km", 16.6),
    ])
    def test_a_reading_as_the_console_shows_it_is_understood(self, given: str, unit: str, value: float) -> None:
        assert missions.parse_answer(given, unit) == pytest.approx(value)

    @pytest.mark.parametrize("given", ["", "about seventy", "nan", "1e3", "12.5.1"])
    def test_anything_but_a_plain_number_is_not(self, given: str) -> None:
        assert missions.parse_answer(given, "km") is None

    @pytest.mark.parametrize(("given", "value"), [("79,72", 79.72), ("79,72° E", 79.72), ("1,436.07", 1436.07),
                                                  ("12,345", 12.345)])
    def test_a_single_comma_between_digits_is_a_decimal_comma(self, given: str, value: float) -> None:
        assert missions.parse_answer(given, "deg") == pytest.approx(value)

    @pytest.mark.parametrize(("value", "unit", "fn", "ok"), [
        (79.72, "deg", "subsat_longitude", True), (-181.0, "deg", "subsat_longitude", False),
        (0.04, "deg", "inclination_deg", True), (-0.04, "deg", "inclination_deg", False),
        (181.0, "deg", "inclination_deg", False), (-1.0, "count", "", False), (14.0, "count", "", True),
        (1435.93, "min", "period_min", True), (0.0 - 5.0, "min", "period_min", False),
    ])
    def test_an_implausible_reading_is_unreadable(self, value: float, unit: str, fn: str, ok: bool) -> None:
        assert missions.plausible(value, unit, fn) is ok

    def test_degrees_are_compared_the_short_way_round(self) -> None:
        assert missions.answer_error(179.9, -179.9, "deg") == pytest.approx(0.2)
        assert missions.answer_error(179.9, -179.9, "km") == pytest.approx(359.8)

    def test_the_accepted_answer_is_written_as_the_console_writes_it(self) -> None:
        assert missions.accepted_text(79.7213, "deg", "subsat_longitude") == "79.72° E"
        assert missions.accepted_text(-0.5, "deg", "subsat_longitude") == "0.50° W"
        assert missions.accepted_text(12.0, "count") == "12"

    def test_only_a_longitude_gets_a_hemisphere(self) -> None:
        """S4: an inclination was accepted as "0.04° E"."""
        assert missions.accepted_text(0.04, "deg", "inclination_deg") == "0.04°"

    def test_a_miss_says_how_far_in_words_only(self) -> None:
        assert missions.miss_band(0.14, 0.05) == "close"
        assert missions.miss_band(0.16, 0.05) == "far"


class TestStars:
    def test_three_for_every_objective_within_par_no_hints_best_answers(self) -> None:
        assert missions.stars_for(True, 100, 150, 0, True).stars == 3

    def test_two_when_over_par(self) -> None:
        outcome = missions.stars_for(True, 200, 150, 0, True)
        assert outcome.stars == 2
        assert not outcome.reasons[1].earned
        assert outcome.reasons[1].why == "Finished in 3:20 against a par of 2:30."

    def test_a_hint_costs_the_third(self) -> None:
        outcome = missions.stars_for(True, 100, 150, 1, True)
        assert outcome.stars == 2
        assert outcome.reasons[2].why == "1 hint used."
        assert missions.stars_for(True, 100, 150, 2, True).reasons[2].why == "2 hints used."

    def test_times_are_minutes_and_seconds(self) -> None:
        assert [missions.mmss(s) for s in (13, 150, 725)] == ["0:13", "2:30", "12:05"]

    def test_none_without_every_objective_met(self) -> None:
        assert missions.stars_for(False, 10, 150, 0, True).stars == 0


_OLD = ("1 30793U 20001A   26274.50000000  .00000000  00000-0  00000-0 0  9991\n"
        "2 30793   0.0400  95.0000 0002000 270.0000 265.0000  1.00273791 10007")
_NEWER = ("1 30793U 20001A   26280.50000000  .00000000  00000-0  00000-0 0  9998\n"
          "2 30793   0.0400  95.0000 0002000 270.0000 265.0000  1.00273791 10007")


def _bound(tle: str) -> Bound:
    return Bound("asset", "30793", "SKYNET 5A", "blue", tle, "SYNTHETIC")


class TestTheMissionClock:
    def test_sets_past_their_limit_put_it_at_the_newest_epoch(self) -> None:
        now = datetime(2026, 11, 17, tzinfo=UTC)
        assert missions.mission_clock([_bound(_OLD), _bound(_NEWER)], now) == datetime(2026, 10, 7, 12, tzinfo=UTC)

    def test_current_sets_put_it_at_now(self) -> None:
        now = datetime(2026, 10, 1, 13, 0, 0, 500, tzinfo=UTC)
        assert missions.mission_clock([_bound(_OLD)], now) == now.replace(microsecond=0)


class TestTexts:
    def test_placeholders_are_filled_with_names_figures_and_the_clock(self) -> None:
        clock = datetime(2026, 10, 1, 12, tzinfo=UTC)
        text = missions.fill("{a} sits {r:.1f} km off at {clock}.", {"a": {"name": "SJ-21"}}, {"r": 16.62},
                             clock)
        assert text == "SJ-21 sits 16.6 km off at 01 Oct 2026 12:00 UTC."

    def test_a_teaser_leaves_figures_not_yet_computed_unsaid(self) -> None:
        assert missions.teaser("{tug} sits {range_now:.1f} km from {target}.", {"tug": "SJ-21"}) == (
            "SJ-21 sits … km from ….")

    def test_every_alert_and_brief_of_the_campaign_is_short(self) -> None:
        for mission in load_campaign().missions:
            assert len(mission.alert.split()) <= missions.MAX_ALERT_WORDS
            assert all(len(line.split()) <= missions.MAX_BRIEF_WORDS for line in mission.brief)


def test_the_window_runs_seventy_two_hours_from_the_clock() -> None:
    clock = datetime(2026, 10, 1, 12, tzinfo=UTC)
    assert missions.window(clock) == (clock, clock + timedelta(hours=72))


def test_the_points_gate_says_missions_pay_points() -> None:
    from types import SimpleNamespace

    from spectre.training.gamification import next_level_gates

    gates = next_level_gates(SimpleNamespace(current_level=1, total_points=0, axis_points={}, tutorials_completed=[],
                                             scenarios_passed=0, challenges_passed=0))
    assert "mission" in gates[0].how
