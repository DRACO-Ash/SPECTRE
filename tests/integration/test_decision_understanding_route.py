"""The Decision Engine page reads the sweep's Threat Understanding for the bound red track (SPC-171).

The sweep is where ACCESS, the threat range and decide-by are worked out, so
the engine reads the picture the sweep held for the red track it is bound to,
and no other: a picture held for another red track is not used, and with
none the rows read "Understanding not assessed". A picture is read at any
age, with its age at evaluation beside every figure and sentence it feeds
(SPC-181), and the sweep's deadline is read only for the blue asset it was set
for. The engine collects first only for a cue whose outcomes change its recommended response (SPC-204), which its
matrix, reading no Threat band, never gives: the page then says the collection cannot change the recommendation, and
the tests of collect first put the stand-in of tests/unit/_band_stand_in.py in place, with a second response for the
cue to choose between. The probability and confidence the operator posted
reach the engine as posted, whatever the Understanding. The route's clock is fixed here, so no test reads the wall
clock, and UDL is not connected, so none reaches the network.
"""

from __future__ import annotations

import html
import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from spectre.domain import decision
from spectre.domain import threat_understanding as tu
from spectre.domain.custody import Custody
from spectre.domain.decide_by import DecideBy, Due
from spectre.domain.threat_assessment import Band
from spectre.web.routes import decision as decision_routes
from tests.integration.conftest import session_state
from tests.integration.test_decision_input_validation import _evaluate, _form
from tests.unit._band_stand_in import band_moves_a_figure  # noqa: F401 (a fixture, used by name)
from tests.unit._i13 import i13_problems
from tests.unit.test_elset_freshness import _tle

_NOW = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)
_RECORD = "analyst to date and source the intel record"
_NOT_ASSESSED = (
    "Understanding not assessed: the engine reads no picture from the sweep for RX, so nothing fills P or Conf."
)
_DECIDE_BY = "Decide by 15:00 UTC on 4 Nov for BLUE_1: its fastest intercept could arrive at 03:00 UTC on 5 Nov."


def _cue(observation: str = tu.PULL_HISTORY, steps: int = 3, hours: float = 0.5, *, record: bool = False) -> tu.Cue:
    return tu.Cue(observation=observation, dimensions=(tu.Dimension.BEHAVIOUR,), steps=steps, hours=hours,
                  effect="could raise the Threat floor to HIGH", benign=(Band.MINIMAL, Band.CRITICAL),
                  hostile=(Band.HIGH, Band.CRITICAL), record=record)


def _picture(red: str = "RX", understanding: tu.Understanding = tu.Understanding.LOW, **kw: Any) -> Any:
    fields: dict[str, Any] = {
        "red": red, "floor": Band.MEDIUM, "ceiling": Band.CRITICAL, "understanding": understanding,
        "cues": (_cue(), _cue(_RECORD, steps=2, hours=4.0, record=True)), "decide_at": _NOW + timedelta(hours=6),
        "decide_by": _DECIDE_BY, "assessed_at": _NOW - timedelta(minutes=20),
    }
    fields.update(kw)
    return decision.ThreatPicture(**fields)


@pytest.fixture
def held(auth_cookie: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """A red track RX held, its orbit 5 h old at the route's fixed clock; whatever picture a test holds is cleared."""
    from spectre.domain.models import RedTrack

    state = session_state(auth_cookie)
    saved = (list(state.red_tracks), state.threat_picture)
    monkeypatch.setattr(decision_routes, "_utc_now", lambda: _NOW)
    state.red_tracks = [RedTrack("RX", _tle(_NOW - timedelta(hours=5), satno=50322), data_mode="REAL")]
    yield state
    state.red_tracks, state.threat_picture = saved


def _text(page: str) -> str:
    return html.unescape(" ".join(re.sub(r"<[^>]+>", " ", page).split()))


#: A second response, so a cue has two to choose between: F1 Hold, a manoeuvre, and F2 Wait, which does nothing.
_TWO = {"fr_id": ["F1", "F2"], "fr_name": ["Hold", "Wait"], "fr_type": ["manoeuvre", "no_action"],
        "fr_cost": ["0.2", "0.0"], "fr_rev": ["0.8", "1.0"], "fr_time": ["4", "0.5"]}


def _page(client: Any, cookie: str, **form: Any) -> str:
    resp = _evaluate(client, cookie, _form(red_sat="RX", adv_prob=["0.3"], adv_conf=["0.6"], **form))
    assert resp.status_code == 200
    assert "error-msg" not in resp.text
    return resp.text


class TestThePictureTheSweepHolds:
    def test_the_sweep_holds_its_range_understanding_cues_and_decide_by(self) -> None:
        from spectre.web import decision_threat

        situation = tu.Situation(now=_NOW, access=Band.CRITICAL, custody=Custody.HELD, history_truncated=False)
        understanding = tu.assess((), situation, with_cues=True)
        state = type("State", (), {"threat_picture": None})()
        decide = DecideBy(Due.SET, _DECIDE_BY, decide_at=_NOW + timedelta(hours=6), arrival=_NOW + timedelta(hours=18),
                          target="BLUE_1")
        decision_threat.hold_threat_picture(state, "RX", understanding, decide, _NOW)
        assert state.threat_picture == decision.ThreatPicture(
            red="RX", floor=Band.MINIMAL, ceiling=Band.CRITICAL, understanding=tu.Understanding.LOW,
            cues=understanding.cues, decide_at=_NOW + timedelta(hours=6), decide_by=_DECIDE_BY, assessed_at=_NOW,
            target="BLUE_1", arrival=_NOW + timedelta(hours=18),
        )

    def test_a_withheld_decide_by_holds_no_deadline(self) -> None:
        from spectre.web import decision_threat

        situation = tu.Situation(now=_NOW, access=Band.CRITICAL, custody=Custody.HELD, history_truncated=False)
        state = type("State", (), {"threat_picture": None})()
        withheld = DecideBy(Due.NONE, "No decide-by: custody is lost.")
        decision_threat.hold_threat_picture(state, "RX", tu.assess((), situation), withheld, _NOW)
        assert state.threat_picture.decide_at is None and state.threat_picture.arrival is None
        assert state.threat_picture.decide_by == "No decide-by: custody is lost."

    def test_a_sweep_whose_model_failed_holds_nothing(self) -> None:
        from spectre.web import decision_threat

        state = type("State", (), {"threat_picture": _picture()})()
        decision_threat.hold_threat_picture(state, "RX", None, DecideBy(Due.NONE, "No decide-by."), _NOW)
        assert state.threat_picture is None


def _elset(side: str, name: str, satno: int) -> decision.BoundElset:
    return decision.BoundElset(side=side, name=name, stk_name=name, satno=satno, tle="1 x\n2 x",  # type: ignore[arg-type]
                               data_mode="REAL", epoch=None, age_hours=None, limit_hours=None)


def _binding(blue: str | None = None) -> decision.ScenarioBinding:
    return decision.ScenarioBinding(red=_elset("red", "RX", 50322),
                                    blue=None if blue is None else _elset("blue", blue, 40001))


def _state(picture: Any) -> Any:
    return type("State", (), {"threat_picture": picture})()


class TestTheEngineReadsThePictureForItsOwnObjectsAtAnyAge:
    """A picture is read at any age (SPC-181), and its deadline only for the blue asset it was set for."""

    @pytest.mark.parametrize("age", [timedelta(0), timedelta(minutes=29, seconds=59), timedelta(minutes=30),
                                     timedelta(hours=3, minutes=10), timedelta(days=3)])
    def test_a_picture_is_read_at_any_age(self, age: timedelta) -> None:
        """The owner's ruling of 2026-11-05 (concept section 9, decision 9): the age is shown, not used to refuse."""
        from spectre.web import decision_threat

        picture = _picture(assessed_at=_NOW - age)
        assert decision_threat.held_picture(_state(picture), _binding(), _NOW) == picture
        assert not hasattr(decision_threat, "THREAT_PICTURE_MAX_AGE")

    def test_a_picture_assessed_after_the_evaluation_is_not_read(self) -> None:
        """Its age at evaluation cannot be said, so it is not shown."""
        from spectre.web import decision_threat

        late = _picture(assessed_at=_NOW + timedelta(seconds=1))
        assert decision_threat.held_picture(_state(late), _binding(), _NOW) is None
        assert decision_threat.readable_picture(late, "RX", _NOW + timedelta(seconds=1)) == late

    @pytest.mark.parametrize("blue", [None, "BLUE_1"], ids=["no blue asset bound", "the asset it was set for"])
    def test_the_sweeps_deadline_is_read_for_its_own_target_or_with_no_blue_asset_bound(self, blue: str | None) -> None:
        from spectre.web import decision_threat

        picture = _picture(target="BLUE_1")
        assert decision_threat.held_picture(_state(picture), _binding(blue), _NOW) == picture

    def test_a_deadline_set_for_another_blue_asset_is_not_collected_against(self) -> None:
        from spectre.web import decision_threat

        held = decision_threat.held_picture(_state(_picture(target="BLUE_1")), _binding("BLUE_2"), _NOW)
        assert held is not None
        assert (held.decide_at, held.floor, held.ceiling) == (None, Band.MEDIUM, Band.CRITICAL)
        assert held.decide_by == (
            "The sweep's decide-by is for BLUE_1, not BLUE_2, the blue asset bound here, so no deadline is set to "
            "collect against."
        )
        assert held.advice(_NOW).advice is tu.Advice.ACT_ON_CEILING
        assert held.collection_rows(_NOW) == ()
        for sentence in held.decide_by.split(". "):
            assert i13_problems(sentence) == [], sentence


class TestTheEnginePage:
    def test_a_straddle_with_time_says_the_collection_cannot_change_the_recommendation(
        self, client: Any, auth_cookie: str, held: Any,
    ) -> None:
        """SPC-204: the sweep would collect first, but the engine's matrix reads no Threat band, so no collection
        can change its recommended response, and nothing is collected first or listed."""
        held.threat_picture = _picture()
        page = _page(client, auth_cookie, **_TWO)
        text = _text(page)
        assert ('Collecting "pull its element-set history" would narrow the Threat range but cannot change the '
                "recommended response: the outcome matrix reads no Threat band (from the sweep's picture assessed "
                "20 min before this evaluation).") in text
        assert 'data-advice="cannot_change_response"' in page
        assert "Collect first" not in text
        assert "collection to narrow the threat range" not in text
        assert tu.ACTION_LINE_MEANS not in text

    @pytest.mark.usefixtures("band_moves_a_figure")
    def test_with_a_stand_in_letting_the_band_move_figures_a_straddle_collects_first_and_adds_the_analyst_row(
        self, client: Any, auth_cookie: str, held: Any,
    ) -> None:
        held.threat_picture = _picture()
        text = _text(_page(client, auth_cookie, **_TWO))
        assert (
            "Collect first: pull its element-set history, about 30 min, lands before decide-by at 15:00 UTC on 4 Nov."
        ) in text
        assert ("Under its benign outcome the engine recommends Wait (F2); under its hostile outcome, Hold (F1) (from "
                "the sweep's picture assessed 20 min before this evaluation).") in text
        assert tu.ACTION_LINE_MEANS in text
        assert ("Threat range for RX: from MEDIUM to CRITICAL (from the sweep's picture assessed 20 min before this "
                "evaluation, at 08:40 UTC on 4 Nov).") in text
        assert f"{_DECIDE_BY.removesuffix('.')} (from the sweep's picture assessed 20 min before this evaluation)." in text
        assert f"{_RECORD}, 4 h: collection to narrow the threat range" in text

    @pytest.mark.usefixtures("band_moves_a_figure")
    @pytest.mark.parametrize("strategy", ["minimax", "expected_value"])
    def test_the_collection_row_is_listed_never_recommended_or_scored(
        self, client: Any, auth_cookie: str, held: Any, strategy: str,
    ) -> None:
        """Collecting tasks no sensor and moves no figure: it is listed, and the ranking is the operator's rows."""
        held.threat_picture = _picture()
        text = _text(_page(client, auth_cookie, strategy=strategy, **_TWO))
        assert "Not ranked against your responses" in text
        assert f"{_RECORD} Type:" not in text and "Type: Sensor Retask" not in text
        assert "1 adversary action(s) and the remainder of P × 2 response(s)" in text
        assert "collect first Hold" not in text and "minimax recommends analyst" not in text.lower()

    def test_the_same_range_with_decide_by_passed_acts_on_the_ceiling(
        self, client: Any, auth_cookie: str, held: Any,
    ) -> None:
        held.threat_picture = _picture(decide_at=_NOW - timedelta(minutes=5))
        text = _text(_page(client, auth_cookie))
        assert "Act on the ceiling: treat it as Threat CRITICAL." in text
        assert ("and decide-by has passed. No collection the picture holds can change the recommended response: the "
                "outcome matrix reads no Threat band (from the sweep's picture assessed 20 min before this "
                "evaluation).") in text
        assert "collection to narrow the threat range" not in text

    def test_a_picture_held_for_another_red_track_is_not_used(self, client: Any, auth_cookie: str, held: Any) -> None:
        held.threat_picture = _picture(red="RY")
        text = _text(_page(client, auth_cookie))
        assert "Collect first" not in text and "Threat range for" not in text
        assert _NOT_ASSESSED in text

    @pytest.mark.usefixtures("band_moves_a_figure")
    def test_a_picture_hours_old_is_read_with_its_age_beside_every_figure_it_feeds(
        self, client: Any, auth_cookie: str, held: Any,
    ) -> None:
        """SPC-181: the threat lines, the collect-first advice and rows, the guidance and the decide-by each say how
        old the picture was at evaluation. The action line's own sentence is not fed by the picture and has none."""
        held.threat_picture = _picture(assessed_at=_NOW - timedelta(hours=3, minutes=10))
        page = _page(client, auth_cookie, strategy="expected_value", **_TWO)
        age = "(from the sweep's picture assessed 3 h 10 min before this evaluation"
        block = page[page.index('class="threat-context"'):]
        block = block[:block.index("</div>")]
        paragraphs = [_text(p) for p in re.findall(r"<p[^>]*>(.*?)</p>", block, re.S)]
        # range, Understanding, decide-by, advice, what the action line is, one row, guidance
        assert len(paragraphs) == 7
        assert paragraphs[4] == tu.ACTION_LINE_MEANS
        assert all(age in p for n, p in enumerate(paragraphs) if n != 4)
        assert paragraphs[0].endswith(f"{age}, at 05:50 UTC on 4 Nov).")
        assert paragraphs[2] == f"{_DECIDE_BY.removesuffix('.')} {age})."
        assert paragraphs[3].startswith("Collect first:") and paragraphs[3].endswith(f"{age}).")
        assert paragraphs[5].startswith(f"{_RECORD}, 4 h:") and f"a lookup {age}). Not ranked" in paragraphs[5]
        assert paragraphs[6].startswith(f"Expected value rests on a probability the evidence has not earned {age}).")
        notes = [html.unescape(n) for n in re.findall(r'class="row-understanding"[^>]*>([^<]*)<', page)]
        assert notes and all(n.endswith(f"{age}).") for n in notes)
        assert _NOT_ASSESSED not in _text(page)

    def test_a_decide_by_passed_at_an_old_sweep_is_restated_against_the_evaluation(
        self, client: Any, auth_cookie: str, held: Any,
    ) -> None:
        """The sweep worded its passed decide-by against its own clock, "2.0 h from now". Read 3 d later, the page
        counts nothing from the sweep: it says when the deadline was and that the intercept could have arrived."""
        from types import SimpleNamespace

        from spectre.domain.decide_by import ResponseTimes, decide_by
        from spectre.web import decision_threat

        swept = _NOW - timedelta(days=3)
        entry = SimpleNamespace(burn_epoch=swept, tof_hours=2.0, delta_v_m_s=10.0, arrives=True,
                                target=SimpleNamespace(target_name="BLUE_1"))
        decide = decide_by([entry], ResponseTimes(sign_in=4.0), swept, 100.0)
        assert decide.due is Due.PASSED and "2.0 h from now" in decide.sentence
        situation = tu.Situation(now=swept, access=Band.CRITICAL, custody=Custody.HELD, history_truncated=False)
        decision_threat.hold_threat_picture(held, "RX", tu.assess((), situation, with_cues=True), decide, swept)
        text = _text(_page(client, auth_cookie))
        assert ("Decide-by has passed for BLUE_1: it was 07:00 UTC on 1 Nov, and the intercept it was set against "
                "could have arrived at 11:00 UTC on 1 Nov, before this evaluation (from the sweep's picture assessed 3 d "
                "before this evaluation).") in text
        assert "from now" not in text and "Decide by " not in text

    def test_with_no_picture_the_page_says_only_what_the_engine_holds(
        self, client: Any, auth_cookie: str, held: Any,
    ) -> None:
        """No picture read is all the engine knows: it never says whether a sweep was run."""
        held.threat_picture = None
        text = _text(_page(client, auth_cookie, strategy="expected_value"))
        assert _NOT_ASSESSED in text
        assert "no threat sweep" not in text.lower()
        assert ("Expected value rests on a probability no Threat picture for RX supports. Minimax, the "
                "cautious rule") in text

    @pytest.mark.parametrize("level", list(tu.Understanding))
    def test_probability_and_confidence_reach_the_engine_as_posted(
        self, client: Any, auth_cookie: str, held: Any, level: tu.Understanding,
    ) -> None:
        held.threat_picture = _picture(understanding=level)
        text = _text(_page(client, auth_cookie))
        assert "P=0.3 (judgement) · Share=0.3 (judgement) · Conf=0.6 (judgement)" in text
        assert (f"Understanding {level.name}: shown beside P and Conf as context; it fills neither (from the sweep's "
                "picture assessed 20 min before this evaluation).") in text

    def test_expected_value_at_understanding_low_names_minimax(self, client: Any, auth_cookie: str, held: Any) -> None:
        held.threat_picture = _picture()
        text = _text(_page(client, auth_cookie, strategy="expected_value"))
        assert ("Expected value rests on a probability the evidence has not earned (from the sweep's picture assessed "
                "20 min before this evaluation). Minimax, the cautious rule") in text

    def test_every_new_sentence_on_the_page_keeps_i13(self, client: Any, auth_cookie: str, held: Any) -> None:
        held.threat_picture = _picture()
        page = _page(client, auth_cookie, strategy="expected_value")
        block = page[page.index('class="threat-context"'):]
        block = block[:block.index("</div>")]
        notes = re.findall(r'class="row-understanding"[^>]*>([^<]*)<', page)
        assert notes
        for chunk in (*re.findall(r">([^<]+)<", block), *notes):
            for sentence in html.unescape(chunk).split(". "):
                assert i13_problems(sentence) == [], sentence


class TestAProbabilityNotPosted:
    def test_a_row_posted_with_no_probability_takes_the_engines_default_and_reads_as_untouched(
        self, client: Any, auth_cookie: str, held: Any,
    ) -> None:
        """Never the Understanding: the engine's default, which the guidance then reads as not earned."""
        held.threat_picture = _picture(understanding=tu.Understanding.HIGH)
        form = _form(red_sat="RX", adv_prob=[], adv_conf=["0.6"], strategy="expected_value")
        resp = _evaluate(client, auth_cookie, form)
        assert resp.status_code == 200 and "error-msg" not in resp.text
        text = _text(resp.text)
        default = f"{decision.DEFAULT_PROBABILITY:g}"
        assert f"P={default} (lookup) · Share={default} (lookup) · Conf=0.6 (judgement)" in text
        assert "Expected value rests on a probability the evidence has not earned." in text


class TestThePanelDefault:
    def test_the_panels_probability_is_the_engines_default_and_never_the_understanding(
        self, client: Any, auth_cookie: str, held: Any,
    ) -> None:
        resp = client.get("/plan/decision/panel", cookies={"spectre_session": auth_cookie})
        held.threat_picture = _picture(understanding=tu.Understanding.HIGH)
        again = client.get("/plan/decision/panel", cookies={"spectre_session": auth_cookie})
        values = re.findall(r'name="adv_prob" value="([^"]*)"', resp.text)
        assert values and set(values) == {f"{decision.DEFAULT_PROBABILITY:g}"}
        assert again.text == resp.text
