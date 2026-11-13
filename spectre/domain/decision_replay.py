"""Decision Engine: replay a recommendation from its stored inputs (SPC-193, evaluation F-02, gate G2).

A record's stored inputs rebuild its Scenario, which is evaluated again under the stored rule, as the console
evaluates it: evaluate_tree, which is evaluate_scenario for one turn. Sampling is seeded from each hypothesis, so
identical inputs repeat exactly (evaluation probe P-15). The replay is set against the record, field by field:

● the record's own rule and code version columns against those inside its hashed inputs, which a rehashed edit to
  either would leave apart, and, where either holds one, the responses its responses column marks not permitted
  against those its stored inputs mark (SPC-195);
● the recommendation shown, the deployment's primary rule's pick; the rule used's pick; each rule's pick on the
  matrix; and a tree's turn-1 pick;
● every input hash the record holds against the replay's own, which a rehashed edit to the stored inputs cannot
  match, since the hashes sit in a column of their own;
● every composite score, compared exactly at full precision.

The replay runs with no wall-time budget. An evaluation whose budget ran out, a row refused or a tree built in part,
is replayed in full, so what the budget left out may differ: the stored inputs say whether it ran out, and the report
says so before comparing anything and again in its verdict. A record written by another code version is replayed
across versions, and the report says so first, from the version inside the hashed inputs. A record written by 0.28.0
or 0.29.0 was evaluated with each row weighed by its P over the rows' sum and no remainder of P (SPC-203): its stored
inputs read under that rule, so the replay reproduces what the operator was shown, and the report says so first too.
So does a record written by 0.28.0 to 0.31.0, evaluated before SPC-202 with no element-set error in any closest
approach: it is replayed under that rule, and the report says so first. So does a record of a game tree written by
0.28.0 to 0.36.0, built over equal turns before SPC-187 let the engine set them from the rows' burn times: it is
replayed over equal turns, as it was built. So does a record of a game tree written by 0.28.0 to 0.37.0, checked
before SPC-188 against the matrix's cost cap, which the tree shared then: it is checked against that cap again, so a
tree refused for its cost is refused again. Nothing here imports the web layer.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal

import spectre
from spectre.domain.decision import (
    FriendlyResponse,
    MissRule,
    ProbabilityRule,
    Scenario,
    ScenarioResult,
    SelectorStrategy,
    TreeCap,
    TurnRule,
)
from spectre.domain.decision_inputs import StoredInputs
from spectre.domain.decision_tree import evaluate_tree
from spectre.domain.rule_comparison import RULE_WORDS, RULES, label, matrix_picks

#: What a replay evaluates with: the console's own evaluate_tree, or a test's stand-in.
Evaluate = Callable[[Scenario, SelectorStrategy], ScenarioResult]
SAME_VERSION = "This record was written by SPECTRE {version}, the version running."
ACROSS_VERSIONS = (
    "This record was written by SPECTRE {recorded} and the running code is {running}: the replay is compared across "
    "versions, so a difference may come from the code rather than the inputs."
)
#: Said first for a record 0.28.0 or 0.29.0 wrote: it is replayed under the rule it was evaluated under (SPC-203).
LEGACY_SHARES = (
    "This record was evaluated before SPC-203, when expected value weighed each row by its P over the sum of the "
    "rows' P, which could exceed 1, and weighed no remainder of P as no adversary action. Its stored inputs say so, "
    "and the replay evaluates it under that rule, as it was evaluated then; this code evaluates a new scenario with "
    "the rows' P summing to at most 1 and the remainder weighed as a row of its own."
)
#: Said first for a record 0.28.0 to 0.31.0 wrote: it is replayed under the miss rule it was evaluated under (SPC-202).
LEGACY_POINT = (
    "This record was evaluated before SPC-202, when no closest approach held element-set error: a computed miss was "
    "scored as it stood, and a sampled band covered the burn's spread alone. Its stored inputs say so, and the "
    "replay evaluates it under that rule, as it was evaluated then; this code draws each object's element-set error "
    "in every sample and scores a computed miss on the lower edge of its element-set band."
)
#: Said first for a record of a game tree 0.28.0 to 0.36.0 wrote: it is replayed over its equal turns (SPC-187).
LEGACY_TURNS = (
    "This record's game tree was built before SPC-187, over equal turns, the span searched split equally among them. "
    "Its stored inputs say so, and the replay builds it over those turns, as it was built then; this code sets each "
    "turn from the rows' burn times, so every burn falls inside its own turn."
)
#: Said first for a record of a game tree 0.28.0 to 0.37.0 wrote: it is checked against the shared cap (SPC-188).
LEGACY_CAP = (
    "This record's game tree was checked before SPC-188 against the matrix's cost cap, which the tree shared then. Its "
    "stored inputs say so, and the replay checks it against that cap, as it was checked then; this code checks a tree "
    "against a cap of its own, set from trees measured under load."
)
BUDGET_RAN_OUT = (
    "The evaluation recorded ran out of its time budget, so part of it was not sampled or built; the replay runs in "
    "full, with no budget, so what the budget left out may differ."
)
_MATCHES = (
    "Replay{across} matches the record exactly: the recommendation, every pick, every score ({n}) and every input "
    "hash ({h})."
)
_DIFFERS = "Replay{across} does not match the record: {k} of {n} comparisons differ.{why}"
_DIFFERS_BUDGET = (
    " The evaluation recorded ran out of its time budget, so a difference may come from what it left out."
)
_ACROSS = " across versions"
#: The two sides of a check of the record's own columns against its stored inputs.
_COLUMN_SIDES = ("the record says", "its stored inputs say")
#: How a record keeps a name: a replayed one is put in the same form before it is compared.
Kept = Callable[[str], str]
#: An id and name, as a record holds a response; None where it holds none.
Named = tuple[str, str] | None
#: One input hash as a record holds it: its label, SHA-256 and epoch.
Hash = Mapping[str, str | None]
#: What a comparison sets against what: a column against the inputs, a pick, an input hash or a score. Checks and
#: picks are always reported; an input hash or a score only when it differs.
Kind = Literal["check", "pick", "hash", "score"]


@dataclass(frozen=True)
class Recorded:
    """What a record holds beside its stored inputs: the rule used's pick, each rule's pick on the matrix and a
    tree's turn-1 pick, each as (id, name) or None; its rule and code version columns; its input hashes; the
    deployment's primary rule, None when it holds none; and each response its responses column marks not permitted,
    as (id, name, reason), none for a record from before vetoes (SPC-195)."""

    recommended:   Named
    picks:         Mapping[SelectorStrategy, Named]
    tree_pick:     Named
    rule:          str
    code_version:  str
    input_hashes:  tuple[Hash, ...]
    primary:       SelectorStrategy | None
    not_permitted: tuple[tuple[str, str, str], ...] = ()


@dataclass(frozen=True)
class Comparison:
    """One thing the record holds, set against what the replay or its stored inputs say, in the report's words."""

    what:     str
    recorded: str
    replayed: str
    kind:     Kind = "pick"
    sides:    tuple[str, str] = ("recorded", "replayed")

    @property
    def same(self) -> bool:
        return self.recorded == self.replayed

    @property
    def line(self) -> str:
        verdict = "same." if self.same else "DIFFERS."
        return f"{self.what}: {self.sides[0]} {self.recorded}, {self.sides[1]} {self.replayed}: {verdict}"


@dataclass(frozen=True)
class Replay:
    """A replay set against its record: the versions, whether the budget ran out, and every comparison in order."""

    recorded_version: str
    running_version:  str
    comparisons:      tuple[Comparison, ...]
    budget_ran_out:   bool = False
    #: Whether the record was evaluated under the rule 0.28.0 and 0.29.0 weighed P by (SPC-203).
    legacy_shares:    bool = False
    #: Whether the record was evaluated under the miss rule of 0.28.0 to 0.31.0 (SPC-202).
    legacy_point:     bool = False
    #: Whether the record is a game tree built over the equal turns of 0.28.0 to 0.36.0 (SPC-187).
    legacy_turns:     bool = False
    #: Whether the record is a game tree checked against the shared cost cap of 0.28.0 to 0.37.0 (SPC-188).
    legacy_cap:       bool = False

    @property
    def across_versions(self) -> bool:
        return self.recorded_version != self.running_version

    @property
    def matches(self) -> bool:
        return all(c.same for c in self.comparisons)

    @property
    def preamble(self) -> tuple[str, ...]:
        """What is said before anything is compared: the version line, the lines saying a record of 0.28.0 to 0.36.0
        is replayed under the rules it was evaluated by, and the budget line when it ran out."""
        return _first_lines(self.recorded_version, self.running_version, budget_ran_out=self.budget_ran_out,
                            legacy=(self.legacy_shares, self.legacy_point, self.legacy_turns, self.legacy_cap))

    @property
    def report(self) -> tuple[str, ...]:
        """Each check and pick, each input hash and score that differs, then the verdict."""
        shown = [c.line for c in self.comparisons if c.kind in {"check", "pick"} or not c.same]
        return (*shown, self._verdict())

    @property
    def lines(self) -> tuple[str, ...]:
        return (*self.preamble, *self.report)

    def _verdict(self) -> str:
        across = _ACROSS if self.across_versions else ""
        if self.matches:
            count = {kind: sum(c.kind == kind for c in self.comparisons) for kind in ("score", "hash")}
            return _MATCHES.format(across=across, n=count["score"], h=count["hash"])
        differ = sum(not c.same for c in self.comparisons)
        why = _DIFFERS_BUDGET if self.budget_ran_out else ""
        return _DIFFERS.format(across=across, k=differ, n=len(self.comparisons), why=why)


def version_line(recorded: str, running: str) -> str:
    """Whether the record was written by the code running, said before anything is replayed."""
    if recorded == running:
        return SAME_VERSION.format(version=recorded)
    return ACROSS_VERSIONS.format(recorded=recorded, running=running)


def _first_lines(
    recorded: str, running: str, *, budget_ran_out: bool,
    legacy: tuple[bool, bool, bool, bool] = (False, False, False, False),
) -> tuple[str, ...]:
    lines = (LEGACY_SHARES, LEGACY_POINT, LEGACY_TURNS, LEGACY_CAP)
    said = [line for line, held in zip(lines, legacy, strict=True) if held]
    return (version_line(recorded, running), *said, *((BUDGET_RAN_OUT,) if budget_ran_out else ()))


def _legacy(stored: StoredInputs) -> bool:
    """Whether *stored* was evaluated under the rule 0.28.0 and 0.29.0 weighed P by (SPC-203)."""
    return stored.scenario.probability_rule is ProbabilityRule.SHARES


def _legacy_point(stored: StoredInputs) -> bool:
    """Whether *stored* was evaluated under the miss rule of 0.28.0 to 0.31.0, no element-set error (SPC-202)."""
    return stored.scenario.miss_rule is MissRule.POINT


def _legacy_turns(stored: StoredInputs) -> bool:
    """Whether *stored* is a game tree built over the equal turns of 0.28.0 to 0.36.0 (SPC-187); one turn has none."""
    return stored.scenario.turns > 1 and stored.scenario.turn_rule is TurnRule.EQUAL


def _legacy_cap(stored: StoredInputs) -> bool:
    """Whether *stored* is a game tree checked against the shared cost cap of 0.28.0 to 0.37.0 (SPC-188); one turn has
    no tree to check."""
    return stored.scenario.turns > 1 and stored.scenario.tree_cap is TreeCap.SHARED


def said_first(stored: StoredInputs, running: str) -> tuple[str, ...]:
    """What a replay of *stored* says before it evaluates anything, read from the hashed inputs alone: the version
    that wrote them against *running*, whether it was evaluated under the rule 0.28.0 and 0.29.0 weighed P by, whether
    under the miss rule of 0.28.0 to 0.31.0, whether a game tree built over equal turns, whether one checked against
    the shared cost cap, and whether the evaluation recorded ran out of its time budget."""
    return _first_lines(stored.code_version, running, budget_ran_out=stored.budget_ran_out,
                        legacy=(_legacy(stored), _legacy_point(stored), _legacy_turns(stored), _legacy_cap(stored)))


def input_hashes(result: ScenarioResult) -> list[dict[str, str | None]]:
    """Every input hash in *result*'s provenance, in its order, as a record holds them; none with no provenance."""
    if result.provenance is None:
        return []
    return [
        {"label": ref.label, "sha256": ref.sha256, "epoch": None if ref.epoch is None else ref.epoch.isoformat()}
        for ref in result.provenance.inputs
    ]


def _named(pair: Named) -> str:
    return "no pick" if pair is None else f"{pair[1]} ({pair[0]})"


def _tree_pick(result: ScenarioResult) -> FriendlyResponse | None:
    selection = None if result.tree is None else result.tree.selection
    first = None if selection is None or not selection.picks else selection.picks[0].pick
    return None if first is None else result.scenario.friendly_responses[first]


def _checks(stored: StoredInputs, recorded: Recorded, kept: Kept) -> list[Comparison]:
    """The record's own rule and code version columns against those its hashed inputs hold, and, where either marks
    a response not permitted, the record's responses column against the stored inputs (SPC-195)."""
    checks = [
        Comparison("Rule used", _rule_words(recorded.rule), RULE_WORDS[stored.rule], kind="check", sides=_COLUMN_SIDES),
        Comparison("Code version", recorded.code_version, stored.code_version, kind="check", sides=_COLUMN_SIDES),
    ]
    vetoed = tuple((r.id, r.name, r.veto_reason) for r in stored.scenario.friendly_responses if r.vetoed)
    if recorded.not_permitted or vetoed:
        stored_text = _vetoes_text(tuple((kept(i), kept(n), kept(why)) for i, n, why in vetoed))
        checks.append(Comparison("Not permitted", _vetoes_text(recorded.not_permitted), stored_text, kind="check",
                                 sides=_COLUMN_SIDES))
    return checks


def _vetoes_text(vetoes: tuple[tuple[str, str, str], ...]) -> str:
    """Responses marked not permitted, each as its name, id and reason, in order; "none" for none."""
    return "; ".join(f"{name} ({rid}): {why}" for rid, name, why in vetoes) or "none"


def _rule_words(value: str) -> str:
    """A rule column's value in the report's words; a value that names no rule, as it stands."""
    return next((RULE_WORDS[rule] for rule in RULES if rule.value == value), value)


def _picks(stored: StoredInputs, recorded: Recorded, result: ScenarioResult, kept: Kept) -> list[Comparison]:
    rule, replayed = stored.rule, matrix_picks(result)

    def said(response: FriendlyResponse | None) -> str:
        return "no pick" if response is None else kept(label(response))

    found = []
    if recorded.primary is not None:
        found.append(Comparison(f"Recommendation, the pick of the primary rule, {RULE_WORDS[recorded.primary]}",
                                _named(recorded.picks.get(recorded.primary)), said(replayed[recorded.primary])))
    found.append(Comparison(f"Pick of the rule used, {RULE_WORDS[rule]}", _named(recorded.recommended),
                            said(None if replayed[rule] is None else result.robust_best_response)))
    found += [
        Comparison(f"{RULE_WORDS[r].capitalize()}'s pick", _named(recorded.picks.get(r)), said(replayed[r]))
        for r in RULES
    ]
    if stored.scenario.turns > 1:
        found.append(Comparison(f"Tree's turn-1 pick ({RULE_WORDS[rule]})", _named(recorded.tree_pick),
                                said(_tree_pick(result))))
    return found


def _hash_text(entry: Hash | None) -> str:
    if entry is None:
        return "none"
    epoch = entry.get("epoch")
    return f"{entry.get('label')}: {entry.get('sha256')}" + ("" if epoch is None else f", epoch {epoch}")


def _hashes(recorded: Recorded, result: ScenarioResult) -> list[Comparison]:
    """Each input hash the record holds against the replay's own, in order; a missing one on either side is none."""
    replayed = input_hashes(result)
    held = recorded.input_hashes
    return [
        Comparison(f"Input hash {k + 1}", _hash_text(held[k] if k < len(held) else None),
                   _hash_text(replayed[k] if k < len(replayed) else None), kind="hash")
        for k in range(max(len(held), len(replayed)))
    ]


def _scores(stored: StoredInputs, result: ScenarioResult) -> list[Comparison]:
    """Every score, row by row as the replay evaluated them, the remainder row's last where the rows leave one
    (SPC-203); the stored inputs hold a score row for each, which their reader checks."""
    return [
        Comparison(
            f"Score, row {i + 1} ({action.id}), response {j + 1} ({response.id})", repr(stored.scores[i][j]),
            repr(result.outcome_matrix[i][j].composite_score), kind="score",
        )
        for i, action in enumerate(result.scenario.adversary_actions)
        for j, response in enumerate(result.scenario.friendly_responses)
    ]


def _as_given(text: str) -> str:
    return text


def replay(
    stored: StoredInputs, recorded: Recorded, *, evaluate: Evaluate | None = None, running: str | None = None,
    kept: Kept = _as_given,
) -> Replay:
    """Evaluate *stored*'s scenario again under its rule and set the result against *recorded* and the stored
    scores; *running* is the code version running, this package's own unless given. *kept* turns a replayed
    response's name into the form the record keeps names in, so the two compare alike."""
    run = evaluate_tree if evaluate is None else evaluate
    result = run(stored.scenario, stored.rule)
    return Replay(
        stored.code_version, spectre.__version__ if running is None else running,
        (*_checks(stored, recorded, kept), *_picks(stored, recorded, result, kept), *_hashes(recorded, result),
         *_scores(stored, result)),
        budget_ran_out=stored.budget_ran_out, legacy_shares=_legacy(stored), legacy_point=_legacy_point(stored),
        legacy_turns=_legacy_turns(stored), legacy_cap=_legacy_cap(stored),
    )
