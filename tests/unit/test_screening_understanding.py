"""Screening with cached history: RANGE and UNDERSTANDING beside the verdict (SPC-169).

Concept section 7.2. Each actor's Threat range and Understanding are read
from what SPECTRE already holds: its intel record, its GCAT row and a
history Pattern of Life has already cached. Nothing is fetched. An actor
with no cached history reads "Understanding LOW: no history held" and its
cue is to pull it. The disagreement sentence gains a case: the legacy
verdict outside the range, or a range read at its ceiling above the legacy
verdict. The verdict column, and the existing disagreement, are unchanged.
"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from spectre.domain import threat_understanding as tu
from spectre.domain.custody import Custody
from spectre.domain.threat_assessment import (
    AccessEvidence,
    ActorRange,
    ActorVerdict,
    Band,
    CapabilityEvidence,
    assess_threat,
    rank_actors,
)
from spectre.web.routes import gcat, pol, threat
from spectre.web.routes.pol import HeldHistory
from tests.unit._i13 import i13_problems
from tests.unit.test_threat_understanding_sweep import (
    _FETCHED,
    _RAISES,
    _SATNO,
    _held_history,
    _satcat,
    cache,  # noqa: F401
)


def _verdict(name: str, satno: str, hours: float, level: str, span: ActorRange | None = None) -> ActorVerdict:
    assessment = assess_threat(
        AccessEvidence(best_delta_v_m_s=8.0, time_to_arrival_hours=hours, method="vbar_hop", regime="GEO"),
        CapabilityEvidence(intel_threat_level=level),
    )
    return ActorVerdict(actor_name=name, actor_satno=satno, assessment=assessment, warning_hours=hours,
                        delta_v_m_s=8.0, method="vbar_hop", country="CHN", understanding=span)


def _high_access_actor() -> ActorVerdict:
    """RED-LEO at 50 m/s and 48 h: ACCESS HIGH, verdict MEDIUM."""
    assessment = assess_threat(
        AccessEvidence(best_delta_v_m_s=50.0, time_to_arrival_hours=48.0, method="vbar_hop", regime="GEO"),
        CapabilityEvidence(intel_threat_level="MEDIUM"),
    )
    return ActorVerdict(actor_name="RED-LEO", actor_satno=_SATNO, assessment=assessment, warning_hours=48.0,
                        delta_v_m_s=50.0, method="vbar_hop", country="CHN")


def _span(floor: Band, ceiling: Band, level: str = "LOW", *, held: bool = True,
          at_ceiling: bool | None = None) -> ActorRange:
    wide = level == "LOW" or int(ceiling) - int(floor) + 1 >= 4
    return ActorRange(floor=floor, ceiling=ceiling, understanding=level, history_held=held,
                      at_ceiling=wide if at_ceiling is None else at_ceiling)


class TestTheActorRange:
    def test_the_range_reads_threat_floor_to_ceiling(self) -> None:
        assert _span(Band.HIGH, Band.CRITICAL).range_label == "Threat HIGH to CRITICAL"
        assert _span(Band.MEDIUM, Band.MEDIUM).range_label == "Threat MEDIUM"

    def test_understanding_says_when_no_history_is_held(self) -> None:
        assert _span(Band.MINIMAL, Band.CRITICAL, held=False).understanding_label == (
            "Understanding LOW: no history held")
        assert _span(Band.HIGH, Band.CRITICAL, "MODERATE").understanding_label == "Understanding MODERATE"

    @pytest.mark.parametrize(("floor", "ceiling", "level"), [
        (Band.CRITICAL, Band.LOW, "LOW"), (Band.LOW, Band.HIGH, "SURE"),
    ])
    def test_a_range_upside_down_or_an_unknown_level_is_refused(self, floor: Band, ceiling: Band,
                                                                level: str) -> None:
        with pytest.raises(ValueError, match="range|Understanding"):
            ActorRange(floor=floor, ceiling=ceiling, understanding=level, history_held=True, at_ceiling=True)


class TestTheNewDisagreementCase:
    def test_a_wide_range_at_understanding_low_above_the_verdict(self) -> None:
        result = rank_actors([
            _verdict("TJS-3", "43874", 6.2, "CRITICAL", _span(Band.MINIMAL, Band.CRITICAL)),
            _verdict("SJ-21", "49330", 3.1, "MEDIUM", _span(Band.MINIMAL, Band.CRITICAL, held=False)),
        ])
        assert result.understanding_disagreement == (
            "SJ-21's Threat is assessed MEDIUM, but its Threat ceiling is CRITICAL and it could arrive in 3.1 h. "
            "SJ-21 reads Understanding LOW: no history held.")

    def test_a_legacy_verdict_outside_the_range(self) -> None:
        result = rank_actors([
            _verdict("TJS-3", "43874", 6.2, "MEDIUM", _span(Band.HIGH, Band.CRITICAL, "MODERATE")),
        ])
        assert result.understanding_disagreement == (
            "TJS-3's Threat is assessed MEDIUM by the current rule, outside the Threat range its evidence "
            "earns, HIGH to CRITICAL, and it could arrive in 6.2 h.")

    def test_a_verdict_above_the_ceiling_is_outside_too(self) -> None:
        result = rank_actors([_verdict("SJ-17", "41838", 14.0, "CRITICAL", _span(Band.MINIMAL, Band.MINIMAL,
                                                                                "MODERATE"))])
        assert "outside the Threat range its evidence earns, MINIMAL to MINIMAL" not in result.understanding_disagreement
        assert result.understanding_disagreement.startswith(
            "SJ-17's Threat is assessed CRITICAL by the current rule, outside the Threat range its evidence earns, "
            "MINIMAL,")

    def test_the_soonest_of_several_is_named(self) -> None:
        result = rank_actors([
            _verdict("A", "1", 9.0, "MEDIUM", _span(Band.MINIMAL, Band.CRITICAL)),
            _verdict("B", "2", 2.0, "HIGH", _span(Band.MINIMAL, Band.CRITICAL)),
            _verdict("C", "3", 1.0, "CRITICAL", _span(Band.MINIMAL, Band.CRITICAL)),
        ])
        assert result.understanding_disagreement.startswith("B's Threat is assessed HIGH")

    @pytest.mark.parametrize("span", [
        None, _span(Band.MINIMAL, Band.CRITICAL), _span(Band.HIGH, Band.CRITICAL, "MODERATE", at_ceiling=False),
    ])
    def test_no_case_when_the_verdict_sits_in_the_range_and_is_not_read_up(self, span: ActorRange | None) -> None:
        assert rank_actors([_verdict("TJS-3", "43874", 6.2, "CRITICAL", span)]).understanding_disagreement == ""

    def test_a_ceiling_above_the_verdict_is_no_case_unless_the_range_is_read_at_it(self) -> None:
        """Finding 12: the second case needs the range read at its ceiling, not merely a ceiling above the verdict."""
        quiet = _span(Band.MINIMAL, Band.CRITICAL, "MODERATE", at_ceiling=False)
        assert rank_actors([_verdict("TJS-3", "43874", 6.2, "HIGH", quiet)]).understanding_disagreement == ""
        read_up = _span(Band.MINIMAL, Band.CRITICAL, "MODERATE", at_ceiling=True)
        assert rank_actors([_verdict("TJS-3", "43874", 6.2, "HIGH", read_up)]).understanding_disagreement.startswith(
            "TJS-3's Threat is assessed HIGH, but its Threat ceiling is CRITICAL")

    def test_a_verdict_on_the_floor_is_inside_the_range(self) -> None:
        on_floor = _span(Band.MEDIUM, Band.CRITICAL, "MODERATE", at_ceiling=False)
        assert rank_actors([_verdict("TJS-3", "43874", 6.2, "MEDIUM", on_floor)]).understanding_disagreement == ""

    def test_of_two_arriving_together_the_cheaper_is_named(self) -> None:
        wide = _span(Band.MINIMAL, Band.CRITICAL)
        result = rank_actors([replace(_verdict("DEAR", "1", 3.0, "MEDIUM", wide), delta_v_m_s=9.0),
                              replace(_verdict("CHEAP", "2", 3.0, "MEDIUM", wide), delta_v_m_s=4.0)])
        assert result.understanding_disagreement.startswith("CHEAP's Threat")

    def test_the_existing_disagreement_is_unchanged(self) -> None:
        plain = [_verdict("TJS-3", "43874", 6.2, "CRITICAL"), _verdict("SJ-21", "49330", 3.1, "MEDIUM")]
        spanned = [replace(v, understanding=_span(Band.MINIMAL, Band.CRITICAL)) for v in plain]
        assert rank_actors(spanned).disagreement == rank_actors(plain).disagreement
        assert [v.actor_satno for v in rank_actors(spanned).ranked] == [v.actor_satno for v in rank_actors(plain).ranked]

    def test_i13_no_shared_sentence_and_no_bare_band(self) -> None:
        cases = [
            [_verdict("SJ-21", "49330", 3.1, "MEDIUM", _span(Band.MINIMAL, Band.CRITICAL, held=False))],
            [_verdict("TJS-3", "43874", 6.2, "MEDIUM", _span(Band.HIGH, Band.CRITICAL, "MODERATE"))],
        ]
        for verdicts in cases:
            text = rank_actors(verdicts).understanding_disagreement
            for sentence in re.split(r"(?<=\.)\s+", text):
                assert i13_problems(sentence) == [], sentence


# ── The route: what is cached is read, nothing is fetched ──

def _no_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    async def refused(*_a: Any, **_k: Any) -> None:
        pytest.fail("screening fetched a history")

    monkeypatch.setattr(pol, "_fetch_and_analyse", refused)
    monkeypatch.setattr(threat, "held_history", refused)


@pytest.fixture
def held(monkeypatch: pytest.MonkeyPatch, cache: Any) -> Any:  # noqa: F811
    """An actor with an intel record and a cached GCAT row; its history may or may not be held."""
    _no_fetch(monkeypatch)
    history = _held_history(_RAISES)
    now = history.pol.records[-1].epoch + timedelta(hours=1)
    monkeypatch.setattr(threat, "get_intel", lambda _s: {"assessed_threat": "Inspector", "threat_level": "MEDIUM",
                                                         "source": "CSIS 2025"})
    cache["satcat"] = _satcat([{"Satcat": _SATNO, "Bus": "Luch"}], _FETCHED)
    state = SimpleNamespace(elset_histories={}, pol_reserve_resets={}, hrr_tle_data_mode={_SATNO: "REAL"})
    return SimpleNamespace(history=history, now=now, state=state)


def _actor_verdict() -> ActorVerdict:
    return _verdict("RED-LEO", _SATNO, 3.1, "MEDIUM")


class TestTheScreenReadsWhatIsCached:
    def test_an_uncached_history_reads_no_history_held_and_its_cue_is_to_pull_it(self, held: Any) -> None:
        span = threat._actor_range(held.state, _actor_verdict(), "LEO", "", held.now)
        assert span is not None
        assert (span.understanding, span.history_held) == ("LOW", False)
        assert span.understanding_label == "Understanding LOW: no history held"
        assert span.cue.startswith("pull its element-set history")

    def test_a_cached_history_raises_understanding(self, held: Any) -> None:
        tle = held.history.pol.records[-1].tle
        without = threat._actor_range(held.state, _actor_verdict(), "LEO", tle, held.now)
        held.state.elset_histories[int(_SATNO)] = HeldHistory(int(_SATNO), held.now, pol=held.history.pol)
        with_history = threat._actor_range(held.state, _actor_verdict(), "LEO", tle, held.now)
        assert without is not None and with_history is not None
        assert with_history.history_held is True
        assert (without.understanding, with_history.understanding) == ("LOW", "MODERATE")
        # The unprecedented burn in the history raises the Threat floor; without it nothing does.
        assert (without.floor, with_history.floor) == (Band.MINIMAL, Band.HIGH)

    def test_a_failure_reads_as_no_range_and_stays_in_the_log(
            self, held: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        def broken(*_a: Any, **_k: Any) -> None:
            raise RuntimeError("internal detail\nforged line")

        monkeypatch.setattr(threat.tu, "assess", broken)
        with caplog.at_level("WARNING", logger=threat.logger.name):
            assert threat._actor_range(held.state, _actor_verdict(), "LEO", "", held.now) is None
        assert all("\nforged line" not in r.getMessage() for r in caplog.records)

    def test_every_screened_actor_carries_its_range_and_the_verdict_is_unchanged(
            self, held: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        verdict = _actor_verdict()
        monkeypatch.setattr(threat, "_screen_one_actor", lambda *_a: (verdict, []))
        monkeypatch.setattr(threat, "_resolve_hrr_tle", lambda *_a: "tle")
        actor = SimpleNamespace(actor_name="RED-LEO", actor_satno=_SATNO, regime="LEO")
        run = threat._screen_all_actors(held.state, [actor], "", None, held.now, 500.0)  # type: ignore[arg-type, list-item]
        (screened,) = run.verdicts
        assert screened.understanding is not None and screened.understanding.history_held is False
        assert replace(screened, understanding=None) == verdict
        assert screened.verdict_label == verdict.verdict_label

    def test_the_range_is_bounded_by_the_actors_own_access(self, held: Any) -> None:
        """Finding 11: an actor whose ACCESS is HIGH reads a Threat ceiling of HIGH, not the geometry's widest."""
        verdict = _high_access_actor()
        assert verdict.assessment.access_label == "HIGH"
        span = threat._actor_range(held.state, verdict, "LEO", "", held.now)
        assert span is not None and span.ceiling is Band.HIGH

    def test_the_actors_verdict_reaches_the_model(self, held: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """ACCESS, the legacy verdict, the data mode and the cost "no burns" is judged against are the actor's own."""
        seen: dict[str, Any] = {}
        assess, history_items = tu.assess, tu.history_items

        def spy_assess(items: Any, situation: tu.Situation, **kw: Any) -> tu.ThreatUnderstanding:
            seen["situation"] = situation
            return assess(items, situation, **kw)

        def spy_history(signals: tu.HistorySignals, **kw: Any) -> tuple[tu.EvidenceItem, ...]:
            seen["dv"] = kw["access_delta_v_m_s"]
            return history_items(signals, **kw)

        monkeypatch.setattr(threat.tu, "assess", spy_assess)
        monkeypatch.setattr(threat.tu, "history_items", spy_history)
        held.state.elset_histories[int(_SATNO)] = HeldHistory(int(_SATNO), held.now, pol=held.history.pol)
        held.state.hrr_tle_data_mode[_SATNO] = "SIMULATED"
        verdict = _high_access_actor()
        assert threat._actor_range(held.state, verdict, "LEO", "", held.now) is not None
        situation = seen["situation"]
        assert (situation.access, situation.legacy, situation.data_mode) == (Band.HIGH, Band.MEDIUM, "SIMULATED")
        assert seen["dv"] == 50.0

    def test_with_a_history_held_the_cue_is_the_best_one_spectre_can_act_on(self, held: Any) -> None:
        """Finding 13, and finding 1: the top fed cue, never a conjunction SPECTRE cannot read.

        With no GCAT row cached, two fed cues are left, the catalogue and the record, so the order shows.
        """
        gcat._CACHE.pop("satcat")
        held.state.elset_histories[int(_SATNO)] = HeldHistory(int(_SATNO), held.now, pol=held.history.pol)
        span = threat._actor_range(held.state, _actor_verdict(), "LEO", held.history.pol.records[-1].tle, held.now)
        assert span is not None
        assert span.cue == ("pull its GCAT catalogue entry: would firm up Identity and move no Threat band, "
                            "0 Threat steps, about 15 min")

    def test_an_uncached_actor_read_at_its_ceiling_raises_the_new_case(self, held: Any) -> None:
        """Finding 12, end to end: Understanding LOW reads the ceiling, so a MEDIUM verdict under CRITICAL is named."""
        verdict = _actor_verdict()
        span = threat._actor_range(held.state, verdict, "LEO", "", held.now)
        assert span is not None and span.at_ceiling is True
        assert rank_actors([replace(verdict, understanding=span)]).understanding_disagreement == (
            "RED-LEO's Threat is assessed MEDIUM, but its Threat ceiling is CRITICAL and it could arrive in 3.1 h. "
            "RED-LEO reads Understanding LOW: no history held.")

    def test_custody_is_judged_on_the_actor_set_by_the_sweeps_rule(self, held: Any) -> None:
        held.state.elset_histories[int(_SATNO)] = HeldHistory(int(_SATNO), held.now, pol=held.history.pol)
        unreadable = threat._actor_range(held.state, _actor_verdict(), "LEO", "", held.now)
        fresh = threat._actor_range(held.state, _actor_verdict(), "LEO", held.history.pol.records[-1].tle, held.now)
        assert unreadable is not None and fresh is not None
        assert f"custody {Custody.LOST.value}" in unreadable.statement
        assert "custody" not in fresh.statement
