"""P-14: edge inputs through the engine, and whether UDL element sets are checksum-checked before they reach it.

Property tested: each edge input either fails loudly (an exception), or degrades with a flag the operator sees (a
refusal or note in the result and on the rendered results page, quoted), and never silently yields a confident
recommendation. Cases: a 30-day-old element set; deep-space (SDP4) objects bound as red and as blue; decayed objects;
NaN and missing inputs, including an injected NaN lookup figure; a stated observation no row gives (contradictory);
extreme priors (P 0 and P 1, every row at 0 under expected value). For gate G9: element sets fetched from UDL are
traced from spectre/web/routes/udl.py (fetch_tle_for_satno) through the quick-add routes and the background refresh
into the session, the binder and BoundElset, with a corrupted (checksum-failing) element set injected at the HTTP
client.

Scenarios are built and driven the way the repository's own tests drive them: tests/unit/test_decision_sampled.py
(_scenario, _never, _page), tests/unit/test_decision_tree_select.py (_still), the binder
spectre/web/decision_binding.py (bound_elset, bind_scenario) and spectre.domain.decision.evaluate_scenario,
spectre.domain.decision_tree.evaluate_tree. The only fault injections are the NaN lookup (pytest monkeypatch of the
_BASE_CA_KM table for one test) and a fake httpx.AsyncClient for the UDL path (no network); no repository file changes.

Framework reference: decision-engine-evaluation-framework.md section 2, test programme row "Adversarial and edge
cases" ("Stale TLEs, NaN or missing lookups, decayed objects, deep-space SDP4 branch, contradictory observations,
extreme priors"), section 1g; evaluation probe 14; gates G6, G9 and G10.

Expected result: every case raises or carries a visible flag; a UDL element set with a bad checksum is refused
before binding. Each test asserts that property, so a silent case shows as a failure.

Each test writes evaluation/evidence/physics/p14_<case>.json (and the rendered page text where one is rendered)
before it asserts, so the evidence survives a pass or a fail.
"""

from __future__ import annotations

import os
import tempfile

# Before anything imports the web layer: the settings it reads, and a scratch data directory outside the tree.
os.environ.setdefault("SECRET_KEY", "probe-p14-secret-key-value")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("SPECTRE_DATA_DIR", tempfile.mkdtemp(prefix="spectre-p14-data-"))

import asyncio  # noqa: E402
import dataclasses  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

import pytest  # noqa: E402
import sgp4  # noqa: E402

from spectre.astro.propagator import TLEOrbit, regime_from_tle, tle_checksum_valid  # noqa: E402
from spectre.domain import decision  # noqa: E402
from spectre.domain.decision import (  # noqa: E402
    ActionType,
    AdversaryAction,
    AdversaryHypothesis,
    FriendlyResponse,
    PreManoeuvreState,
    Scenario,
    ScenarioBinding,
    ScenarioResult,
    SelectorStrategy,
    Seen,
    evaluate_scenario,
)
from spectre.domain.decision_tree import evaluate_tree  # noqa: E402
from spectre.domain.models import BlueAsset, RedTrack  # noqa: E402
from spectre.web.decision_binding import bind_scenario, bound_elset  # noqa: E402
from spectre.web.planning_state import SessionState  # noqa: E402
from tests.unit._decision_reference import (  # noqa: E402
    EPOCH,
    EPOCH_DAY,
    GEO_DRIFT_IN,
    PLANE_CHANGE,
    _checksum,
    element_set,
)
from tests.unit.test_decision_sampled import _never, _page, _scenario  # noqa: E402
from tests.unit.test_decision_tree_select import _still  # noqa: E402

_EVIDENCE = Path(__file__).resolve().parents[1] / "evidence" / "physics"
_VER = Path(sgp4.__file__).parent / "SGP4-VER.TLE"
_EV = SelectorStrategy.EXPECTED_VALUE
_MINIMAX = SelectorStrategy.MINIMAX


# ── Helpers ─────────────────────────────────────────────────────────────────

def _record(name: str, data: dict[str, Any], page: str | None = None) -> None:
    """Write the case's evidence and print it, before any assertion."""
    _EVIDENCE.mkdir(parents=True, exist_ok=True)
    (_EVIDENCE / f"p14_{name}.json").write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    if page is not None:
        (_EVIDENCE / f"p14_{name}_page.txt").write_text(page, encoding="utf-8")
    print(f"\nP-14 {name}: " + json.dumps(data, default=str))


def _with_check(line: str) -> str:
    return line[:68] + _checksum(line[:68])


def _redate(tle_lines: tuple[str, str], epoch_day: str = EPOCH_DAY) -> str:
    """A verification element set with its epoch moved to *epoch_day*, both checksums made good."""
    line1, line2 = tle_lines
    return f"{_with_check(line1[:18] + epoch_day + line1[32:68])}\n{_with_check(line2[:68])}"


def _ver(satnum: str) -> tuple[str, str]:
    lines = _VER.read_text(encoding="ascii").splitlines()
    k = next(i for i, x in enumerate(lines) if x.startswith(f"1 {satnum}"))
    return lines[k].rstrip().ljust(69), lines[k + 1][:69]


def _epoch_day_plus(days: float) -> str:
    whole = float(EPOCH_DAY) + days
    return f"{whole:014.8f}"


def _bind(red_tle: str, blue_tle: str, now: datetime) -> ScenarioBinding:
    """The binder's own BoundElset for each side, aged at *now* (spectre/web/decision_binding.py:56-71)."""
    return ScenarioBinding(
        red=bound_elset("red", RedTrack(name="PROBE_RED", tle=red_tle, data_mode="REAL"), now),
        blue=bound_elset("blue", BlueAsset(name="PROBE_BLUE", tle=blue_tle, data_mode="REAL"), now),
    )


def _flags(result: ScenarioResult) -> dict[str, Any]:
    """Everything the result says about its own standing, beside the recommendation."""
    refusals = sorted({c.ca_refusal for row in result.outcome_matrix for c in row if c.ca_refusal})
    binding = result.scenario.binding
    return {
        "recommendation": result.robust_best_response.name,
        "strategy": result.robust_strategy.value,
        "composite_scores": [[c.composite_score for c in row] for row in result.outcome_matrix],
        "closest_approach_km": [[c.closest_approach_km for c in row] for row in result.outcome_matrix],
        "bases": [[c.figure_bases.closest_approach_km.kind.value for c in row] for row in result.outcome_matrix],
        "modelled_banner": result.modelled,
        "basis_lines": list(result.basis_lines),
        "row_notes": [n for n in result.row_notes if n],
        "cell_refusals": refusals,
        "binding_sentences": [] if binding is None else [b.sentence for b in binding.bound],
        "computed_caveat": result.computed_caveat,
        "searched_span_note": result.searched_span_note,
        "objective_guidance": result.objective_guidance,
    }


def _mentions(page: str, words: tuple[str, ...]) -> dict[str, bool]:
    low = page.lower()
    return {w: w.lower() in low for w in words}


def _three(scenario: Scenario) -> Scenario:
    """The test's 4 x 4 scenario with its rows reordered last-first, to see whether a pick follows row order."""
    return dataclasses.replace(scenario, friendly_responses=list(reversed(scenario.friendly_responses)))


# ── 1. A stale element set: 30 days old ─────────────────────────────────────

def test_p14_stale_elset_30_days() -> None:
    now = EPOCH + timedelta(days=30)
    blue_now = element_set(PLANE_CHANGE.blue, epoch_day=_epoch_day_plus(30))
    binding = _bind(PLANE_CHANGE.red_tle, blue_now, now)
    red_state = TLEOrbit(PLANE_CHANGE.red_tle).propagate(now)
    hyp = AdversaryHypothesis.from_archetype(
        "evasive", PreManoeuvreState(now, (*red_state.r, *red_state.v)), n_samples=50,
    )
    scenario = dataclasses.replace(_scenario({0: hyp}, binding=binding, horizon_hours=6.0), epoch_utc=now)
    result = evaluate_scenario(scenario, sampler=_never)   # _never: the sampler must not run
    page = _page(result)
    data = {"red_age_hours": binding.red.age_hours, "red_limit_hours": binding.red.limit_hours,
            "red_freshness": binding.red.freshness.value, **_flags(result),
            "page_mentions": _mentions(page, ("out of date", "Modelled estimate", "lookup"))}
    _record("stale_30_days", data, page)
    assert binding.red.freshness.value == "out of date"
    assert data["cell_refusals"] or data["modelled_banner"], "a 30-day-old element set produced no flag"


# ── 2. Deep-space objects (SDP4) bound as red and as blue ───────────────────

def _deep_case(label: str, red_tle: str, blue_tle: str, horizon_h: float) -> dict[str, Any]:
    binding = _bind(red_tle, blue_tle, EPOCH)
    scenario = _scenario(binding=binding, horizon_hours=horizon_h)
    result = evaluate_scenario(scenario, sampler=_never)
    page = _page(result)
    data = {
        "label": label,
        "red_method": TLEOrbit(red_tle)._sat.method, "blue_method": TLEOrbit(blue_tle)._sat.method,  # noqa: SLF001
        "red_period_min": round(2 * math.pi / TLEOrbit(red_tle)._sat.no_kozai, 1),  # noqa: SLF001
        "blue_period_min": round(2 * math.pi / TLEOrbit(blue_tle)._sat.no_kozai, 1),  # noqa: SLF001
        "red_regime": regime_from_tle(red_tle), "blue_regime": regime_from_tle(blue_tle),
        "red_limit_hours": binding.red.limit_hours, "blue_limit_hours": binding.blue.limit_hours,
        **_flags(result),
        "page_mentions": _mentions(page, ("SDP4", "deep space", "deep-space", "lunar", "solar", "envelope")),
    }
    _record(f"deep_space_{label}", data, page)
    return data


def test_p14_deep_space_geo_pair_red_and_blue() -> None:
    data = _deep_case("geo_pair", GEO_DRIFT_IN.red_tle, GEO_DRIFT_IN.blue_tle, 24.0)
    assert data["red_method"] == "d" and data["blue_method"] == "d"
    assert any(data["page_mentions"].values()), "deep-space objects evaluated with no flag naming the regime"


def test_p14_deep_space_molniya_red_against_leo_blue() -> None:
    molniya = _redate(_ver("08195"))
    data = _deep_case("molniya_red", molniya, PLANE_CHANGE.blue_tle, 6.0)
    assert data["red_method"] == "d"
    assert any(data["page_mentions"].values()), "a deep-space red evaluated with no flag naming the regime"


# ── 3. Decayed objects ──────────────────────────────────────────────────────

def _decaying() -> str:
    """SGP4-VER case 28872 (error 6, decayed, at 55 min) re-dated to EPOCH with good checksums."""
    return _redate(_ver("28872"))


def _decay_map(tle: str, minutes: int) -> list[list[int]]:
    """Contiguous minute ranges after epoch in which the wrapper raises an SGP4 error."""
    orbit, bad = TLEOrbit(tle), []
    for m in range(minutes + 1):
        try:
            orbit.propagate(EPOCH + timedelta(minutes=m))
        except RuntimeError:
            if bad and bad[-1][1] == m - 1:
                bad[-1][1] = m
            else:
                bad.append([m, m])
    return bad


def test_p14_decayed_within_the_window() -> None:
    """Scenario epoch at the element set's epoch; SGP4 reports decay 52 to 55 minutes in."""
    tle = _decaying()
    binding = _bind(tle, PLANE_CHANGE.blue_tle, EPOCH)
    result = evaluate_scenario(_scenario(binding=binding, horizon_hours=6.0), sampler=_never)
    page = _page(result)
    data = {"decay_error_minutes": _decay_map(tle, 360)[:4], "red_freshness": binding.red.freshness.value,
            **_flags(result), "page_mentions": _mentions(page, ("decay", "propagat", "re-ent", "lookup"))}
    _record("decayed_within_window", data, page)
    assert data["cell_refusals"], "a decaying red produced no refusal"


def test_p14_decayed_before_the_scenario_between_perigee_errors() -> None:
    """The same element set, the scenario starting 70 minutes after its epoch, over 1 h.

    SGP4 raises its decay code only while the radius is under one Earth radius, so between perigee passes it
    returns states again. The window 70 to 130 minutes holds no error instant.
    """
    tle = _decaying()
    start = EPOCH + timedelta(minutes=70)
    binding = _bind(tle, PLANE_CHANGE.blue_tle, start)
    scenario = dataclasses.replace(_scenario(binding=binding, horizon_hours=1.0), epoch_utc=start)
    result = evaluate_scenario(scenario, sampler=_never)
    page = _page(result)
    orbit = TLEOrbit(tle)
    alts = [orbit.propagate(start + timedelta(minutes=m)).altitude_km for m in range(61)]
    data = {"decay_error_minutes": _decay_map(tle, 240), "red_age_hours": binding.red.age_hours,
            "red_freshness": binding.red.freshness.value,
            "red_altitude_km_min_max_in_window": [min(alts), max(alts)],
            **_flags(result),
            "page_mentions": _mentions(page, ("decay", "re-ent", "reentry", "below the surface", "below 100 km",
                                              "Karman"))}
    _record("decayed_before_scenario", data, page)
    computed = [b for row in data["bases"] for b in row if b == "computed"]
    about_red = [r for r in data["cell_refusals"] if "red element set" in r or "decay" in r]
    assert not computed or about_red or any(data["page_mentions"].values()), (
        "a decayed object yielded a computed closest approach with no flag"
    )


def test_p14_decayed_blue_refuses_a_sampled_row() -> None:
    """A hypothesis on red, blue decayed at the window start: the sampled row's pre-run checks."""
    tle = _decaying()
    start = EPOCH + timedelta(minutes=55)   # inside the first error interval
    binding = _bind(PLANE_CHANGE.red_tle, tle, start)
    red_state = TLEOrbit(PLANE_CHANGE.red_tle).propagate(start)
    hyp = AdversaryHypothesis.from_archetype(
        "evasive", PreManoeuvreState(start, (*red_state.r, *red_state.v)), n_samples=50,
    )
    scenario = dataclasses.replace(_scenario({0: hyp}, binding=binding, horizon_hours=1.0), epoch_utc=start)
    result = evaluate_scenario(scenario, sampler=_never)
    data = _flags(result)
    _record("decayed_blue_sampled_row", data)
    assert data["row_notes"] or data["cell_refusals"]


# ── 4. NaN and missing values ───────────────────────────────────────────────

def _raises(build: Any) -> str:
    try:
        build()
    except (ValueError, TypeError) as exc:
        return f"{type(exc).__name__}: {exc}"
    return "no exception"


def test_p14_nan_inputs_fail_loudly() -> None:
    base = _scenario()
    a, f = base.adversary_actions[0], base.friendly_responses[0]
    nan = float("nan")
    data = {
        "AdversaryAction.probability=NaN": _raises(lambda: dataclasses.replace(a, probability=nan)),
        "AdversaryAction.confidence=NaN": _raises(lambda: dataclasses.replace(a, confidence=nan)),
        "AdversaryAction.custody_gap_fraction=NaN": _raises(lambda: dataclasses.replace(a, custody_gap_fraction=nan)),
        "FriendlyResponse.cost=NaN": _raises(lambda: dataclasses.replace(f, cost=nan)),
        "FriendlyResponse.reversibility=NaN": _raises(lambda: dataclasses.replace(f, reversibility=nan)),
        "FriendlyResponse.time_to_execute_hours=NaN": _raises(lambda: dataclasses.replace(f, time_to_execute_hours=nan)),
        "Scenario.w_custody=NaN": _raises(lambda: dataclasses.replace(base, w_custody=nan)),
        "Scenario.horizon_hours=NaN": _raises(lambda: dataclasses.replace(base, horizon_hours=nan)),
    }
    _record("nan_inputs", data)
    assert all(v != "no exception" for v in data.values())


def test_p14_all_weights_zero_and_missing_form_fields() -> None:
    """Every weight 0 (each is a valid fraction, and the web layer leaves all-zero weights as given), and what the
    web layer does with a weight or a row value the form does not send."""
    from spectre.web.routes import decision as route

    base = _scenario()
    zero = dataclasses.replace(base, w_custody=0.0, w_closest_approach=0.0, w_dv_cost=0.0, w_time_to_exec=0.0,
                               w_reversibility=0.0)
    result = evaluate_scenario(zero, sampler=_never)
    reordered = evaluate_scenario(_three(zero), sampler=_never)
    page = _page(result)
    columns = route._AdversaryColumns(  # noqa: SLF001
        ids=["A0", "A1"], names=["one", "two"], types=["manoeuvre", "no_action"], probs=[0.9], confs=[0.8], gaps=[],
    )
    rows = route._adversary_rows(columns, [None, None])  # noqa: SLF001
    inputs = route._Inputs()  # noqa: SLF001
    inputs.number("", "each scoring weight")
    blank = inputs.problem
    data = {
        **_flags(result),
        "recommendation_with_responses_reversed": reordered.robust_best_response.name,
        "page_mentions": _mentions(page, ("all zero", "every weight", "weights are 0", "no weight", "a tie", "tied")),
        "normalised_all_zero_weights": route._normalised_weights(0.0, 0.0, 0.0, 0.0, 0.0),  # noqa: SLF001
        "form_default_weights_when_field_absent": {
            k: route._ScenarioForm.model_fields[k].default for k in ("w_custody", "w_ca", "w_dv", "w_time", "w_rev")  # noqa: SLF001
        },
        "blank_weight_field": blank,
        "row_2_probability_when_form_sends_one_value": rows[1].probability,
        "row_2_confidence_when_form_sends_one_value": rows[1].confidence,
        "row_1_and_2_custody_gap_when_form_sends_none": [r.custody_gap_fraction for r in rows],
    }
    _record("weights_zero_and_missing_fields", data, page)
    flagged = any(data["page_mentions"].values()) or data["objective_guidance"]
    assert flagged or data["recommendation"] == data["recommendation_with_responses_reversed"], (
        "all-zero weights give a recommendation set by row order, with no flag"
    )


def test_p14_nan_lookup_figure_injected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fault injection: the manoeuvre row's lookup closest approach set to NaN for this test only."""
    monkeypatch.setitem(decision._BASE_CA_KM, ActionType.MANOEUVRE, float("nan"))  # noqa: SLF001
    base = _scenario()
    outcome: dict[str, Any] = {}
    try:
        result = evaluate_scenario(base, sampler=_never)
        reordered = evaluate_scenario(_three(base), sampler=_never)
        page = _page(result)
        outcome = {**_flags(result), "recommendation_with_responses_reversed": reordered.robust_best_response.name,
                   "nan_printed_on_page": " nan " in f" {page.lower()} ",
                   "page_mentions": _mentions(page, ("not a number", "missing", "invalid", "undefined"))}
        outcome["exception"] = None
    except Exception as exc:  # noqa: BLE001  recorded, it is the observation
        page = None
        outcome["exception"] = f"{type(exc).__name__}: {exc}"
    _record("nan_lookup_injected", outcome, page)
    assert outcome["exception"] or any(outcome["page_mentions"].values()), "a NaN lookup was scored silently"


# ── 5. Contradictory observations ───────────────────────────────────────────

@pytest.mark.parametrize("strategy", [_EV, _MINIMAX])
def test_p14_contradictory_observation(strategy: SelectorStrategy) -> None:
    """Both rows give 'no burn' under the custody rule; the operator states turn 1 showed 'a burn'."""
    scenario = dataclasses.replace(_still(), observed=Seen.BURN)
    result = evaluate_tree(scenario, strategy)
    tree = result.tree
    assert tree is not None
    selection = tree.selection
    data = {
        "strategy": strategy.value, "tree_refusal": tree.refusal,
        "likelihood": None if selection is None else [s.value for s in selection.likelihood],
        "picks": None if selection is None else [(p.turn, p.pick) for p in selection.picks],
        "update_lines": None if selection is None else list(selection.update),
        "matrix_recommendation": result.robust_best_response.name,
    }
    _record(f"contradictory_observation_{strategy.value}", data)
    assert selection is not None
    assert any("which no row gives" in line or "updated nothing" in line for line in selection.update)


# ── 6. Extreme priors ───────────────────────────────────────────────────────

def _with_p(scenario: Scenario, ps: list[float]) -> Scenario:
    rows = [dataclasses.replace(a, probability=p) for a, p in zip(scenario.adversary_actions, ps, strict=True)]
    return dataclasses.replace(scenario, adversary_actions=rows)


def test_p14_extreme_priors() -> None:
    base = _scenario()
    cases = {"all_zero": [0.0] * 4, "all_one": [1.0] * 4, "row0_one_rest_zero": [1.0, 0.0, 0.0, 0.0],
             "row3_one_rest_zero": [0.0, 0.0, 0.0, 1.0]}
    data: dict[str, Any] = {}
    pages = {}
    for name, ps in cases.items():
        s = _with_p(base, ps)
        ev, mm = evaluate_scenario(s, _EV, sampler=_never), evaluate_scenario(s, _MINIMAX, sampler=_never)
        ev_rev = evaluate_scenario(_three(s), _EV, sampler=_never)
        page = _page(ev)
        pages[name] = page
        best_row = min(range(4), key=lambda j: ev.outcome_matrix[ps.index(1.0)][j].composite_score) if 1.0 in ps else None
        data[name] = {
            "P": ps, "expected_value_pick": ev.robust_best_response.name,
            "expected_value_pick_with_responses_reversed": ev_rev.robust_best_response.name,
            "minimax_pick": mm.robust_best_response.name,
            "objective_guidance": ev.objective_guidance,
            "best_response_of_the_certain_row": None if best_row is None else base.friendly_responses[best_row].name,
            "page_mentions": _mentions(page, ("probability", "no weight", "all zero", "unearned", "has not earned")),
        }
    _record("extreme_priors", data, pages["all_zero"])
    zero = data["all_zero"]
    assert zero["objective_guidance"] or zero["expected_value_pick"] == zero["expected_value_pick_with_responses_reversed"], (
        "every row at P 0 under expected value gives a pick set by row order, with no flag"
    )


# ── 7. G9: are UDL element sets checksum-checked before the engine? ──────────

def _corrupt(tle: str, column: int = 10) -> str:
    """Line 2 with one character of the inclination field changed and its checksum left as it was.

    Column 10 (0-indexed) is the inclination's units digit: 97.4 becomes 98.4 degrees, a plausible orbit one degree
    out, as a single transmission error would leave it. Column 8 is the field's leading blank: 97.4 becomes 597.4.
    """
    line1, line2 = tle.splitlines()
    old = line2[column]
    new = "5" if old == " " else str((int(old) + 1) % 10)
    return f"{line1}\n{line2[:column]}{new}{line2[column + 1:]}"


class _FakeResponse:
    def __init__(self, records: list[dict[str, str]]) -> None:
        self._records = records

    def raise_for_status(self) -> None:
        return None

    def json(self) -> list[dict[str, str]]:
        return self._records


class _FakeClient:
    """Stands in for httpx.AsyncClient inside fetch_tle_for_satno: no network."""

    records: list[dict[str, str]] = []
    calls: list[str] = []

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def get(self, url: str, **_: object) -> _FakeResponse:
        _FakeClient.calls.append(url)
        return _FakeResponse(_FakeClient.records)


def test_p14_udl_elset_checksum_reaches_the_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    from spectre.web import elsets
    from spectre.web.routes import udl

    good = PLANE_CHANGE.red_tle
    bad = _corrupt(good)
    l1, l2 = bad.splitlines()
    monkeypatch.setattr(udl.httpx, "AsyncClient", _FakeClient)
    _FakeClient.records = [{"line1": l1, "line2": l2, "dataMode": "REAL"}]

    # Path 1: fetch_tle_for_satno, then a red track exactly as quick_add_red_track builds it (operator.py:239-251).
    fetched = asyncio.run(udl.fetch_tle_for_satno(90002, "user", "pass"))
    assert fetched is not None
    tle, mode = fetched
    state = SessionState()
    state.red_tracks.append(RedTrack(name="UDL_RED", tle=tle, data_mode=mode))
    state.blue_assets.append(BlueAsset(name="UDL_BLUE", tle=PLANE_CHANGE.blue_tle, data_mode="REAL"))
    now = EPOCH
    bound = bind_scenario(state, state.red_tracks[0].stk_name, state.blue_assets[0].stk_name, now)
    assert bound.binding is not None, bound.problem
    result = evaluate_scenario(_scenario(binding=bound.binding), sampler=_never)
    genuine = evaluate_scenario(_scenario(binding=_bind(good, PLANE_CHANGE.blue_tle, now)), sampler=_never)
    page = _page(result)

    # Path 2: the background refresh at UDL connect replaces a held UDL set with a newer one (elsets.py:147-167).
    newer = _corrupt(element_set(PLANE_CHANGE.red, epoch_day=_epoch_day_plus(0.5)))
    n1, n2 = newer.splitlines()
    _FakeClient.records = [{"line1": n1, "line2": n2, "dataMode": "REAL"}]
    held = SessionState(udl_username="user", udl_password="pass")
    held.red_tracks.append(RedTrack(name="HELD_RED", tle=good, data_mode="REAL"))
    asyncio.run(elsets.refresh_held_elsets(held, "user", "pass"))

    absurd = _corrupt(good, column=8)
    absurd_result = evaluate_scenario(_scenario(binding=_bind(absurd, PLANE_CHANGE.blue_tle, now)), sampler=_never)
    data = {
        "fake_http_calls": list(_FakeClient.calls),
        "genuine_line2": good.splitlines()[1],
        "fetched_line2": tle.splitlines()[1],
        "fetched_checksums_valid": [tle_checksum_valid(x) for x in tle.splitlines()],
        "bound_red_tle_equals_fetched": bound.binding.red.tle == tle,
        "bound_red_checksums_valid": [tle_checksum_valid(x) for x in bound.binding.red.tle.splitlines()],
        "computed_closest_approach_km_corrupted": result.outcome_matrix[3][0].closest_approach_km,
        "computed_closest_approach_km_genuine": genuine.outcome_matrix[3][0].closest_approach_km,
        "recommendation_corrupted": result.robust_best_response.name,
        "recommendation_genuine": genuine.robust_best_response.name,
        "cell_refusals_corrupted": _flags(result)["cell_refusals"],
        "page_mentions": _mentions(page, ("checksum",)),
        "refresh_replaced_held_set": held.red_tracks[0].tle == newer,
        "refresh_outcome": {"updated": held.elset_refresh.updated, "failed": held.elset_refresh.failed},
        "refreshed_checksums_valid": [tle_checksum_valid(x) for x in held.red_tracks[0].tle.splitlines()],
        "side_observation_inclination_597_line2": absurd.splitlines()[1],
        "side_observation_inclination_597_bases": _flags(absurd_result)["bases"][3],
        "side_observation_inclination_597_closest_approach_km": absurd_result.outcome_matrix[3][0].closest_approach_km,
    }
    _record("udl_checksum", data, page)
    assert all(data["bound_red_checksums_valid"]), "a UDL element set failing its checksum reached the engine"
