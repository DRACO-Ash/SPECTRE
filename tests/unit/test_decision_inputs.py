"""The canonical inputs of an evaluation, stored with its decision record (SPC-193, evaluation F-02, gate G2).

Provenance hashed the inputs and stored none, so a recommendation could not be reproduced once the sign-in ended.
Each record now keeps the whole Scenario (rows, responses, weights, horizon, turns, keep-out, observed, every
hypothesis with its dispersions and seed, accepted NOTSO priors, the threat picture, and the binding with each bound
element set's text, epoch, age, limit, data mode and custody), the rule, and the result's composite score matrix, as
one canonical JSON document with its SHA-256. The deserialiser is strict: it refuses an unknown or a missing field, a
schema or version it does not know, a document whose hash does not match, and one not in canonical form.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from spectre.astro.notso import NOTSOType
from spectre.astro.response_burn import BurnAxis
from spectre.domain import threat_understanding as tu
from spectre.domain.custody import Custody, CustodyStatus
from spectre.domain.decision import (
    ActionType,
    AdversaryAction,
    AdversaryHypothesis,
    BoundElset,
    FriendlyResponse,
    Scenario,
    ScenarioBinding,
    ScenarioResult,
    Seen,
    SelectorStrategy,
    ThreatPicture,
    evaluate_scenario,
)
from spectre.domain.decision_figures import ResponseBurnSpec
from spectre.domain.decision_inputs import (
    SCHEMA,
    VERSION,
    InputsRefusedError,
    canonical_json,
    decode_scenario,
    encode_scenario,
    inputs_document,
    read_inputs,
    store_inputs,
)
from spectre.domain.decision_transfer import TransferBurn
from spectre.domain.notso_prior import CountedNotice, NotsoPrior
from spectre.domain.threat_assessment import Band
from tests.unit import _decision_tree_cases as cases
from tests.unit._decision_reference import EPOCH, PLANE_CHANGE
from tests.unit.test_pol_status_ladder import _make_record, _manoeuvre

_BURN_2 = EPOCH + timedelta(minutes=40)
_BURN_3 = EPOCH + timedelta(minutes=70)


def _still_rows() -> list[AdversaryAction]:
    return [
        AdversaryAction("A1", "Approach", ActionType.MANOEUVRE, 0.4, 0.6, description="from the west"),
        AdversaryAction("A2", "Hold", ActionType.NO_ACTION, 0.5, 0.7, probability_edited=False,
                        custody_gap_fraction=0.25),
        AdversaryAction("A3", "Retask", ActionType.SENSOR_RETASK, 0.1, 0.0),
        AdversaryAction("A4", "Posture", ActionType.POSTURE_CHANGE, 1.0, 1.0),
    ]


def _responses() -> list[FriendlyResponse]:
    return [
        FriendlyResponse("F1", "Hold", ActionType.NO_ACTION, 0.0, 1.0, 0.0),
        FriendlyResponse("F2", "Avoid", ActionType.MANOEUVRE, 0.3, 0.8, 2.0, description="raise",
                         burn=ResponseBurnSpec(target_km=20.0)),
        FriendlyResponse("F3", "Avoid radially", ActionType.MANOEUVRE, 0.3, 0.8, 1.5,
                         burn=ResponseBurnSpec(target_km=15.5, budget_km_s=0.0025, axis=BurnAxis.RADIAL)),
        FriendlyResponse("F4", "Retask", ActionType.SENSOR_RETASK, 0.1, 0.9, 1.0),
        FriendlyResponse("F5", "Posture", ActionType.POSTURE_CHANGE, 0.05, 1.0, 0.5),
    ]


def _lookup() -> Scenario:
    return Scenario(
        name="Lookup \x00 \"quoted\" – \U0001f6f0", epoch_utc=EPOCH, adversary_actions=_still_rows(),
        friendly_responses=_responses()[:1] + _responses()[3:], horizon_hours=36.5, w_custody=0.3,
        w_closest_approach=0.3, w_dv_cost=0.2, w_time_to_exec=0.1, w_reversibility=0.1, keep_out_km=12.25,
    )


def _computed() -> Scenario:
    return cases.scenario([cases.still(), cases.still("Retask", "A1", ActionType.SENSOR_RETASK)],
                          [cases.hold(), cases.avoid(None)], turns=1)


def _sampled() -> Scenario:
    return cases.scenario([cases.still(), cases.evasive(n=50, offset_h=1.0)], [cases.hold(), cases.avoid(20.0)],
                          turns=1)


def _entered() -> Scenario:
    at = cases.pre_manoeuvre_state(cases.COPLANAR_LEO.red_tle, EPOCH + timedelta(hours=2))
    assert at is not None
    plain = AdversaryHypothesis.from_entered(4.0, (0.3, 1.0, -0.2), at, n_samples=40)
    spread = AdversaryHypothesis.from_entered(6.0, None, at, archetype="phasing", n_samples=30).with_spread(0.7)
    detected = AdversaryHypothesis.from_detection(_make_record(), _manoeuvre(0.013), archetype="plane_change",
                                                  n_samples=10)
    rows = [
        AdversaryAction("A1", "Entered", ActionType.MANOEUVRE, 0.3, 0.5, hypothesis=plain),
        AdversaryAction("A2", "Spread", ActionType.MANOEUVRE, 0.3, 0.5, hypothesis=spread),
        AdversaryAction("A3", "Detected", ActionType.MANOEUVRE, 0.4, 0.5, hypothesis=detected),
    ]
    return cases.scenario(rows, [cases.hold(), cases.avoid(20.0)], turns=1)


def _transfer() -> Scenario:
    at = cases.pre_manoeuvre_state(PLANE_CHANGE.red_tle, EPOCH)
    assert at is not None
    first = AdversaryHypothesis.from_entered(1.0, (0.0, 1.0, 0.0), at, n_samples=50)
    carried = first.with_transfer((TransferBurn(_BURN_2, 2.0, 0.5, -1.0), TransferBurn(_BURN_3, 1.0, 0.0, 0.0)))
    row = AdversaryAction("A1", "Transfer", ActionType.MANOEUVRE, 0.6, 0.5, hypothesis=carried)
    return cases.scenario([row], [cases.hold()], turns=1, horizon_h=1.0, bind=PLANE_CHANGE)


def _tree(observed: Seen | None = Seen.BURN) -> Scenario:
    red = dataclasses.replace(cases.bound("red"), custody=CustodyStatus(Custody.HELD, "Custody held."))
    rows = [dataclasses.replace(cases.still(), probability=0.25),
            dataclasses.replace(cases.evasive(n=50, offset_h=1.0), probability=0.75)]
    scenario = cases.scenario(rows, [cases.hold(), cases.avoid(20.0)], turns=2,
                              bind=ScenarioBinding(red=red, blue=cases.bound("blue")))
    return dataclasses.replace(scenario, observed=observed)


def _prior(**overrides: Any) -> NotsoPrior:
    fields: dict[str, Any] = {
        "red": "RED_coplanar_leo", "action_type": ActionType.MANOEUVRE, "probability": 0.13, "confidence": 0.3,
        "events": 5, "notices": 6, "span_start": EPOCH - timedelta(days=100), "span_end": EPOCH,
        "covered_days": 100.0, "gaps": 1, "horizon_hours": 72.0,
        "mapped": (NOTSOType.MANOEUVRE, NOTSOType.PROXIMITY_OPS), "confidence_line": "Conf line.", "launched": 2019,
        "cover": ((EPOCH - timedelta(days=100), EPOCH - timedelta(days=40)), (EPOCH - timedelta(days=30), EPOCH)),
        "counted": (CountedNotice(EPOCH - timedelta(days=60), NOTSOType.MANOEUVRE),
                    CountedNotice(EPOCH - timedelta(days=5), NOTSOType.PROXIMITY_OPS)),
        "until": EPOCH,
    }
    fields.update(overrides)
    return NotsoPrior(**fields)


def _with_priors() -> Scenario:
    rows = [
        AdversaryAction("A1", "Approach", ActionType.MANOEUVRE, 0.13, 0.3, accepted_prior=_prior()),
        AdversaryAction("A2", "Hold", ActionType.NO_ACTION, 0.4, 0.2,
                        accepted_prior=_prior(action_type=ActionType.NO_ACTION, probability=0.4, confidence=None,
                                              cover=(), counted=(), until=None, launched=None)),
    ]
    return cases.scenario(rows, [cases.hold()], turns=1)


def _cue(observation: str, *, record: bool = False, fed: bool = True) -> tu.Cue:
    return tu.Cue(observation=observation, dimensions=(tu.Dimension.BEHAVIOUR, tu.Dimension.CAPABILITY), steps=3,
                  hours=0.5, effect="could raise the Threat floor to HIGH", benign=(Band.MINIMAL, Band.CRITICAL),
                  hostile=(Band.HIGH, Band.CRITICAL), record=record, fed=fed)


def _with_picture() -> Scenario:
    scenario = _computed()
    picture = ThreatPicture(
        red="RED_coplanar_leo", floor=Band.MEDIUM, ceiling=Band.CRITICAL, understanding=tu.Understanding.LOW,
        cues=(_cue("pull its history"), _cue("ask an analyst", record=True, fed=False)),
        decide_at=EPOCH + timedelta(hours=6), decide_by="Decide by 18:00 UTC on 17 Oct.", target="BLUE_1",
        arrival=EPOCH + timedelta(hours=9), assessed_at=EPOCH - timedelta(minutes=20),
    )
    return dataclasses.replace(scenario, threat=picture)


def _bound(**red: Any) -> BoundElset:
    return dataclasses.replace(cases.bound("red"), **red)


#: Every kind of row, response and binding the suite builds, by name.
SCENARIOS: dict[str, Any] = {
    "lookup, unbound, every action type": _lookup,
    "computed, both bound": _computed,
    "sampled, an archetype hypothesis": _sampled,
    "entered, spread and detected hypotheses": _entered,
    "multi-burn transfer": _transfer,
    "two-turn tree, turn 1 observed": _tree,
    "three-turn tree, nothing observed": lambda: dataclasses.replace(_tree(None), turns=3),
    "accepted NOTSO priors": _with_priors,
    "threat picture": _with_picture,
    "red only, custody degraded": lambda: dataclasses.replace(_lookup(), binding=ScenarioBinding(
        red=_bound(custody=CustodyStatus(Custody.DEGRADED, "Custody degraded.", basis="basis words"))),
    ),
    "blue only, unreadable epoch, training, no satno": lambda: dataclasses.replace(_lookup(), binding=ScenarioBinding(
        blue=dataclasses.replace(cases.bound("blue"), epoch=None, age_hours=None, limit_hours=None, satno=None,
                                 training=True, data_mode="SIMULATED"))),
    "red out of date, lost": lambda: dataclasses.replace(_lookup(), binding=ScenarioBinding(
        red=_bound(age_hours=40.0, custody=CustodyStatus(Custody.LOST, "Custody lost.")), blue=cases.bound("blue"))),
}


@pytest.fixture(params=list(SCENARIOS), ids=list(SCENARIOS))
def scenario(request: pytest.FixtureRequest) -> Scenario:
    return SCENARIOS[request.param]()  # type: ignore[no-any-return]


def _result(scenario: Scenario, rule: SelectorStrategy = SelectorStrategy.MINIMAX) -> ScenarioResult:
    """A lookup result for *scenario*, cheap to build: the document stores its scores, whatever they rest on."""
    unbound = dataclasses.replace(scenario, binding=None, threat=None, turns=1, observed=None)
    result = evaluate_scenario(unbound, rule)
    return dataclasses.replace(result, scenario=scenario)


class TestRoundTrip:
    def test_every_kind_of_scenario_comes_back_equal(self, scenario: Scenario) -> None:
        back = decode_scenario(json.loads(json.dumps(encode_scenario(scenario))))
        assert back == scenario
        assert encode_scenario(back) == encode_scenario(scenario)

    def test_the_stored_document_gives_back_the_scenario_rule_and_scores(self, scenario: Scenario) -> None:
        result = _result(scenario, SelectorStrategy.EXPECTED_VALUE)
        text, sha256 = store_inputs(result)
        stored = read_inputs(text, sha256)
        assert stored.scenario == scenario
        assert stored.rule is SelectorStrategy.EXPECTED_VALUE
        assert stored.scores == tuple(tuple(c.composite_score for c in row) for row in result.outcome_matrix)
        assert result.provenance is not None
        assert stored.code_version == result.provenance.code_version

    def test_element_set_text_is_kept_verbatim(self) -> None:
        scenario = _computed()
        assert scenario.binding is not None and scenario.binding.red is not None
        tle = "  " + scenario.binding.red.tle + "\n\n"
        odd = dataclasses.replace(scenario, binding=dataclasses.replace(
            scenario.binding, red=dataclasses.replace(scenario.binding.red, tle=tle)))
        back = decode_scenario(json.loads(canonical_json(encode_scenario(odd))))
        assert back.binding is not None and back.binding.red is not None
        assert back.binding.red.tle == tle

    def test_every_hypothesis_figure_and_seed_comes_back_exactly(self) -> None:
        scenario = _entered()
        for original, back in zip(scenario.adversary_actions, decode_scenario(encode_scenario(scenario)).adversary_actions,
                                  strict=True):
            assert original.hypothesis is not None and back.hypothesis is not None
            assert back.hypothesis.recorded() == original.hypothesis.recorded()
            assert back.hypothesis.hypothesis.random_seed == original.hypothesis.hypothesis.random_seed
            assert list(back.hypothesis.hypothesis.pre_manoeuvre_state_eci_km) == list(
                original.hypothesis.hypothesis.pre_manoeuvre_state_eci_km)

    def test_a_hypothesis_with_a_seed_of_its_own_keeps_it(self) -> None:
        scenario = _sampled()
        hypothesis = scenario.adversary_actions[1].hypothesis
        assert hypothesis is not None
        seeded = dataclasses.replace(hypothesis, hypothesis=dataclasses.replace(hypothesis.hypothesis, random_seed=7))
        rows = [scenario.adversary_actions[0], dataclasses.replace(scenario.adversary_actions[1], hypothesis=seeded)]
        back = decode_scenario(encode_scenario(dataclasses.replace(scenario, adversary_actions=rows)))
        assert back.adversary_actions[1].hypothesis is not None
        assert back.adversary_actions[1].hypothesis.hypothesis.random_seed == 7


class TestTheStoredDocument:
    def test_it_is_canonical_json_and_its_hash_is_the_sha256_of_its_text(self) -> None:
        result = _result(_with_picture())
        text, sha256 = store_inputs(result)
        assert sha256 == hashlib.sha256(text.encode("utf-8")).hexdigest()
        assert text == canonical_json(inputs_document(result))
        assert text == json.dumps(json.loads(text), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        assert text.isascii()

    def test_the_same_inputs_store_the_same_text(self) -> None:
        assert store_inputs(_result(_entered())) == store_inputs(_result(_entered()))

    def test_it_names_its_schema_version_rule_scores_and_code_version(self) -> None:
        result = _result(_lookup(), SelectorStrategy.MINIMIN)
        document = json.loads(store_inputs(result)[0])
        assert set(document) == {"schema", "version", "code_version", "rule", "scenario", "scores", "budget_ran_out"}
        assert (document["schema"], document["version"], document["rule"]) == (SCHEMA, VERSION, "minimin")
        assert len(document["scores"]) == 4 and {len(row) for row in document["scores"]} == {3}

    def test_every_character_outside_ascii_is_stored_escaped(self) -> None:
        scenario = dataclasses.replace(_lookup(), name="\u00c9vasion \u2708 \U0001f6f0")
        text, sha256 = store_inputs(_result(scenario))
        assert text.isascii()
        assert "\\u00c9vasion \\u2708 \\ud83d\\udef0" in text
        assert read_inputs(text, sha256).scenario.name == scenario.name

    def test_it_says_whether_the_time_budget_ran_out(self) -> None:
        result = _result(_lookup())
        assert json.loads(store_inputs(result)[0])["budget_ran_out"] is False
        assert read_inputs(*store_inputs(result)).budget_ran_out is False
        cut = dataclasses.replace(result, budget_ran_out=True)
        assert json.loads(store_inputs(cut)[0])["budget_ran_out"] is True
        assert read_inputs(*store_inputs(cut)).budget_ran_out is True

    def test_a_nul_is_stored_escaped_so_both_databases_take_it(self) -> None:
        text, _sha256 = store_inputs(_result(_lookup()))
        assert "\x00" not in text
        assert "\\u0000" in text


def _document(result: ScenarioResult | None = None) -> dict[str, Any]:
    return json.loads(store_inputs(result or _result(_entered()))[0])  # type: ignore[no-any-return]


def _stored(document: dict[str, Any]) -> tuple[str, str]:
    """*document* in canonical form with its own hash, as a record would hold it."""
    text = canonical_json(document)
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest()


def _assert_refused(text: str, sha256: str, *words: str) -> None:
    with pytest.raises(InputsRefusedError) as refused:
        read_inputs(text, sha256)
    for word in words:
        assert word in str(refused.value), str(refused.value)


class TestStrictRefusal:
    def test_a_tampered_document_fails_its_hash(self) -> None:
        text, sha256 = store_inputs(_result(_lookup()))
        tampered = text.replace('"keep_out_km":12.25', '"keep_out_km":99.0')
        assert tampered != text
        _assert_refused(tampered, sha256, "SHA-256")

    def test_a_tampered_score_fails_its_hash(self) -> None:
        document = _document()
        text, sha256 = _stored(document)
        document["scores"][0][0] += 0.125
        _assert_refused(canonical_json(document), sha256, "SHA-256")

    def test_an_unknown_version_is_refused(self) -> None:
        _assert_refused(*_stored({**_document(), "version": VERSION + 1}), "version 2", "knows version 1")

    def test_a_version_that_is_not_a_whole_number_is_refused(self) -> None:
        text, sha256 = _stored({**_document(), "version": 1.0})
        assert '"version":1.0' in text
        _assert_refused(text, sha256, "version 1.0", "knows version 1")

    def test_a_truth_value_is_not_a_score(self) -> None:
        document = _document()
        document["scores"][0][0] = True
        _assert_refused(*_stored(document), "scores[0][0]", "a bool where a number belongs")

    def test_a_code_version_that_is_not_text_is_refused(self) -> None:
        _assert_refused(*_stored({**_document(), "code_version": 27}), "code_version", "where text belongs")

    def test_whether_the_budget_ran_out_must_be_a_truth_value(self) -> None:
        _assert_refused(*_stored({**_document(), "budget_ran_out": 0}), "budget_ran_out", "where bool belongs")

    def test_an_unknown_schema_is_refused(self) -> None:
        _assert_refused(*_stored({**_document(), "schema": "something.else"}), "schema")

    def test_an_unknown_field_is_refused_where_it_is(self) -> None:
        document = _document()
        document["scenario"]["adversary_actions"][0]["hypothesis"]["hypothesis"]["thrust"] = 1.0
        _assert_refused(*_stored(document), "unknown", "thrust", "scenario.adversary_actions[0].hypothesis.hypothesis")

    def test_an_unknown_top_level_field_is_refused(self) -> None:
        _assert_refused(*_stored({**_document(), "note": "x"}), "unknown", "note")

    def test_a_missing_field_is_refused_where_it_is(self) -> None:
        document = _document()
        del document["scenario"]["friendly_responses"][1]["burn"]
        _assert_refused(*_stored(document), "missing", "burn", "scenario.friendly_responses[1]")

    def test_a_missing_top_level_field_is_refused(self) -> None:
        document = _document()
        del document["scores"]
        _assert_refused(*_stored(document), "missing", "scores")

    def test_a_value_of_the_wrong_kind_is_refused(self) -> None:
        document = _document()
        document["scenario"]["name"] = ["not", "text"]
        _assert_refused(*_stored(document), "scenario.name")

    def test_an_unknown_rule_or_enum_value_is_refused(self) -> None:
        _assert_refused(*_stored({**_document(), "rule": "maximin"}), "rule")
        document = _document()
        document["scenario"]["adversary_actions"][0]["action_type"] = "teleport"
        _assert_refused(*_stored(document), "scenario.adversary_actions[0].action_type")

    def test_a_scenario_the_engine_would_refuse_is_refused(self) -> None:
        document = _document()
        document["scenario"]["adversary_actions"][0]["probability"] = 1.5
        _assert_refused(*_stored(document), "not a scenario")

    def test_scores_that_do_not_fit_the_scenario_are_refused(self) -> None:
        document = _document()
        document["scores"] = document["scores"][:-1]
        _assert_refused(*_stored(document), "scores")
        document = _document()
        document["scores"][0] = [*document["scores"][0], 0.5]
        _assert_refused(*_stored(document), "scores")
        document = _document()
        document["scores"][0][0] = "0.5"
        _assert_refused(*_stored(document), "scores")

    def test_a_document_not_in_canonical_form_is_refused(self) -> None:
        document = _document()
        pretty = json.dumps(document, sort_keys=True, indent=1)
        _assert_refused(pretty, hashlib.sha256(pretty.encode("utf-8")).hexdigest(), "canonical")

    def test_a_repeated_key_is_refused(self) -> None:
        text, _sha256 = store_inputs(_result(_lookup()))
        twice = text.replace('{"budget_ran_out"', '{"rule":"minimin","budget_ran_out"', 1)
        assert twice != text
        _assert_refused(twice, hashlib.sha256(twice.encode("utf-8")).hexdigest(), "repeated", "rule")

    @pytest.mark.parametrize("text", ["", "not json", "[1, 2]", "null", '{"schema": 1'])
    def test_what_is_not_a_document_is_refused(self, text: str) -> None:
        _assert_refused(text, hashlib.sha256(text.encode("utf-8")).hexdigest())

    def test_no_stored_hash_is_refused(self) -> None:
        text, _sha256 = store_inputs(_result(_lookup()))
        _assert_refused(text, "", "SHA-256")

    def test_a_refusal_is_a_value_error(self) -> None:
        assert issubclass(InputsRefusedError, ValueError)


def test_a_document_stores_utc_times_with_their_offset() -> None:
    document = _document(_result(_with_priors()))
    assert document["scenario"]["epoch_utc"] == EPOCH.isoformat()
    assert document["scenario"]["epoch_utc"].endswith("+00:00")
    assert datetime.fromisoformat(document["scenario"]["epoch_utc"]).tzinfo == UTC


class TestEveryRefusalNamesItsPlace:
    @pytest.mark.parametrize(("path", "value", "words"), [
        (("scenario", "epoch_utc"), 1700000000, "where text belongs"),
        (("scenario", "epoch_utc"), "yesterday", "not an ISO 8601 time"),
        (("scenario", "adversary_actions"), {}, "where a list belongs"),
        (("scenario", "binding"), "bound", "where an object belongs"),
        (("scenario", "threat", "cues", 0, "benign"), [0], "1 items where a pair belongs"),
        (("scenario", "turns"), True, "where int belongs"),
        (("scenario", "binding", "red", "satno"), "90002", "where int | None belongs"),
    ])
    def test_a_misshapen_value(self, path: tuple[Any, ...], value: Any, words: str) -> None:
        document = _document(_result(_with_picture()))
        place: Any = document
        for step in path[:-1]:
            place = place[step]
        place[path[-1]] = value
        where = ".".join(str(step) for step in path).replace(".0.", "[0].")
        _assert_refused(*_stored(document), words, where)

    def test_a_number_canonical_json_never_holds_is_refused(self) -> None:
        text = canonical_json(_document(_result(_lookup()))).replace('"keep_out_km":12.25', '"keep_out_km":NaN')
        assert "NaN" in text
        _assert_refused(text, hashlib.sha256(text.encode("utf-8")).hexdigest(), "canonical")


class TestTheCodecCoversEveryField:
    def test_a_value_no_codec_names_is_refused_when_written(self) -> None:
        with pytest.raises(TypeError, match="no codec for a object"):
            encode_scenario(dataclasses.replace(_lookup(), name=object()))  # type: ignore[arg-type]

    def test_a_field_of_a_kind_no_codec_reads_is_refused_when_the_module_loads(self) -> None:
        from spectre.domain import decision_inputs

        with pytest.raises(TypeError, match="no codec for a field declared list"):
            decision_inputs._plain("list[int]")
        with pytest.raises(TypeError, match="Scenario has no field nope"):
            decision_inputs._Shape(Scenario, {"nope": decision_inputs._MOMENT})
