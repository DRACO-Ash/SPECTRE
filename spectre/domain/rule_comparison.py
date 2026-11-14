"""Decision Engine: every rule's pick side by side, and the deployment's primary rule (SPC-194, evaluation F-03).

One rule ran per evaluation, chosen on the panel and changeable once a result was seen, and the result showed that
rule's pick alone: an operator could choose the rule that gave the answer they preferred and was not told when the
cautious and the probability-weighted picks differed. Every result is now read under all three rules:

● The picks of minimax, minimin and expected value, each find_robust_response on the result's own matrix, each with
  its rule's one-line meaning, and a line saying whether they agree or, where they do not, which picks differ.
● For a game tree, each rule's turn-1 pick, tree_selectors.select over the tree already built: no new sampling.
● The headline is the deployment's primary rule's pick, set before use; a chosen rule other than the primary is
  shown beside it, so no rule chosen after the fact can hide the primary's answer. The matrix's star marks the rule
  chosen, and a line says so beside the primary rule's pick.
● With every row at P 0, expected value has no weight to pick on: it has no pick, on the matrix as on the tree, and
  is never counted as agreeing with another rule. Since SPC-203 the remainder of P carries the weight the rows
  leave, so this arises only replaying a record 0.28.0 or 0.29.0 wrote, and find_robust_response gives no pick
  there (SPC-200, evaluation F-31), so nothing is starred under it either.
● A response marked not permitted (SPC-195) is never any rule's pick, here or on the tree, and with every response
  so marked no rule has a pick: nothing is recommended and every line says why.
● Beside the headline, its weight stability (SPC-205, evaluation F-16): the smallest change of one weight that
  changes the primary rule's pick, weight_stability's own, the record's too; and the chosen rule's beside it when that
  is another rule. A game tree's picks are not covered, and a line says so.
● The collect-first advice judged by the primary rule's pick, the recommendation shown (SPC-204, evaluation F-14).
● A tie (SPC-206, evaluation F-13): responses whose values under a rule lie within TIE_TOLERANCE of each other are
  each named wherever that rule's pick is, the headline says it is a tie, and rules that find the same tie agree.
  find_robust_response still returns the first, so the pick a record holds is unchanged.

Nothing here changes a figure, a pick or the rule the evaluation ran under: every pick is read from the result.
Imports the Decision Engine and its tree selectors, never the reverse; nothing here imports the web layer.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from dataclasses import dataclass

from spectre.domain.decision import (
    CollectionRow,
    FriendlyResponse,
    Scenario,
    ScenarioResult,
    SelectorStrategy,
    find_robust_response,
    named_list,
    permitted_responses,
    tie_line,
    tied_responses,
)
from spectre.domain.provenance import FigureBasis
from spectre.domain.threat_understanding import CollectionAdvice
from spectre.domain.tree_selectors import TurnPick, select
from spectre.domain.weight_stability import (
    STABILITY_BASIS,
    STABILITY_MARK,
    TREE_NOT_COVERED,
    WeightStability,
    weight_stability,
)

#: The three rules, in the order every result, record and page lists them.
RULES: tuple[SelectorStrategy, ...] = (
    SelectorStrategy.MINIMAX, SelectorStrategy.MINIMIN, SelectorStrategy.EXPECTED_VALUE,
)
#: Each rule in the words the page and the record use.
RULE_WORDS: dict[SelectorStrategy, str] = {rule: rule.value.replace("_", " ") for rule in RULES}
#: Each rule's meaning, in one line.
MEANINGS: dict[SelectorStrategy, str] = {
    SelectorStrategy.MINIMAX: "The cautious rule: the response whose worst case over the rows scores least.",
    SelectorStrategy.MINIMIN: (
        "The optimistic rule, not a robust one: the response whose best case over the rows scores least."
    ),
    SelectorStrategy.EXPECTED_VALUE: (
        "The response whose scores, each row weighted by its P, average least; the one rule that reads P."
    ),
}
#: What the picks rest on.
PICKS_BASIS = "Each rule picks on the same composite scores, those of the matrix below, a lookup."
AGREE = "All three rules agree: each picks {pick}."
DISAGREE = "The rules disagree: {groups}."
TREE_AGREE = "Over the {turns} turns{built}, all three rules agree on turn 1: each picks {pick}."
TREE_DISAGREE = "Over the {turns} turns{built}, the rules disagree on turn 1: {groups}."
#: The tree's line with every response marked not permitted (SPC-195): no rule picks, so none agrees or disagrees.
TREE_NONE_PERMITTED = (
    "Over the {turns} turns{built}, no rule picks a response on turn 1: every response is marked not permitted."
)
#: A tree the budget stopped before its last turn: its picks rest on the turns built in full.
TREE_BUILT = ", built in full to turn {k} only"
#: Why a rule has no pick while some response is permitted: only expected value can have none, when every row has
#: P 0. With every response marked not permitted, every rule has none, and NO_PICK_VETOED says why.
NO_PICK = "has no pick, since every row has P 0"
#: Why no rule has a pick: every response is marked not permitted (SPC-195).
NO_PICK_VETOED = "has no pick, since every response is marked not permitted"
NONE_PERMITTED = "No rule picks a response: every response is marked not permitted."
PRIMARY_CHOSEN = "This deployment's primary rule is {primary}, the rule chosen: the recommendation is its pick, {pick}."
PRIMARY_CHOSEN_NONE = (
    "This deployment's primary rule is {primary}, the rule chosen: it {none}, so no recommendation is shown."
)
PRIMARY_DIFFERS = "This deployment's primary rule is {primary}: {said}. You chose {chosen}: {chosen_said}. {shown}"
SHOWN = "The recommendation shown is the primary rule's pick."
SHOWN_NONE = "No recommendation is shown, since the primary rule has no pick."
#: What the matrix's star and the ranking's highlight mark: the rule chosen's pick, the engine's own.
STAR_PRIMARY = "\u2605 and the blue highlights mark {pick}, the pick of {chosen}, the primary rule and the rule chosen."
STAR_CHOSEN = (
    "\u2605 and the blue highlights mark {pick}, the pick of {chosen}, the rule chosen; the recommendation above is "
    "{primary_pick}, the pick of {primary}, the deployment's primary rule."
)
STAR_CHOSEN_NO_PRIMARY = (
    "\u2605 and the blue highlights mark {pick}, the pick of {chosen}, the rule chosen; the deployment's primary rule, "
    "{primary}, " + NO_PICK + ", so no recommendation is shown above."
)
#: Under expected value with every row at P 0, nothing is starred: the rule has no pick (SPC-200, evaluation F-31).
STAR_NO_WEIGHT = "Nothing is starred: {chosen}, the rule chosen, " + NO_PICK + "."
#: With every response marked not permitted, nothing is starred (SPC-195).
STAR_NOTHING = "Nothing is starred: every response is marked not permitted."
#: Who the chosen rule's weight stability is about, when it is not the primary rule (SPC-205).
CHOSEN_SUBJECT = "{Rule}'s pick, the rule chosen,"


@dataclass(frozen=True)
class RulePick:
    """One rule's pick on the one-turn matrix, None for none, with the rule in words and its meaning."""

    rule:     SelectorStrategy
    response: FriendlyResponse | None
    #: Why the rule has no pick, when it has none: every row at P 0, or every response marked not permitted.
    none:     str = NO_PICK
    #: The pick and every response tied with it under the rule (SPC-206); empty when not worked out.
    tied:     tuple[FriendlyResponse, ...] = ()

    @property
    def words(self) -> str:
        return RULE_WORDS[self.rule]

    @property
    def meaning(self) -> str:
        return MEANINGS[self.rule]

    @property
    def pick_text(self) -> str:
        """The pick as the page names it, a tie naming each tied response, or that the rule has none and why."""
        if self.response is None:
            return self.none.removeprefix("has ")
        return tie_words(self.tied) if len(self.tied) > 1 else label(self.response)


@dataclass(frozen=True)
class RuleComparison:
    """Every rule's pick on a result, whether they agree, and the primary rule's pick as the headline.

    *picks* are the one-turn matrix's, in RULES order; *tree_picks* each rule's turn-1 pick over the tree, None for a
    rule with no pick, and empty for one turn or a tree with no turn built; *tree_agree* None then. *headline* is None
    when the primary rule has no pick. *star_line* says what the matrix's star marks. *caveat* is the guidance the
    results give when expected value's probability is not earned, whatever rule ran; None when it is earned.
    *stability* is the headline's weight stability (SPC-205), *chosen_stability* the chosen rule's pick's when that
    is another rule, else None, and *tree_not_covered* the line saying a tree's picks are not covered, None for one
    turn. *collection* and *collection_rows* are the collect-first advice and rows judged by the primary rule's pick
    (SPC-204), None and none with no Threat picture.
    """

    picks:        tuple[RulePick, ...]
    agree:        bool
    line:         str
    tree_picks:   tuple[tuple[SelectorStrategy, FriendlyResponse | None], ...]
    tree_line:    str | None
    tree_agree:   bool | None
    primary:      SelectorStrategy
    chosen:       SelectorStrategy
    headline:     FriendlyResponse | None
    primary_line: str
    star_line:    str
    caveat:       str | None
    stability:    WeightStability
    chosen_stability: WeightStability | None
    tree_not_covered: str | None
    collection:   CollectionAdvice | None
    collection_rows: tuple[CollectionRow, ...]
    basis:        str = PICKS_BASIS
    stability_basis: str = STABILITY_BASIS
    stability_mark: FigureBasis = STABILITY_MARK
    #: The primary rule's pick and every response tied with it (SPC-206), and the sentence saying it is a tie, None
    #: when there is none.
    headline_tied: tuple[FriendlyResponse, ...] = ()
    tie_line:     str | None = None

    @property
    def differs(self) -> bool:
        """Whether the rule the evaluation ran under is not the deployment's primary rule."""
        return self.chosen is not self.primary


def matrix_picks(result: ScenarioResult) -> dict[SelectorStrategy, FriendlyResponse | None]:
    """Each rule's pick on *result*'s matrix, by find_robust_response; nothing on *result* is changed.

    Expected value has none when every row has P 0, as on the tree (tree_selectors), and find_robust_response says so
    itself (SPC-200). With every response marked not permitted, no rule has a pick.
    """
    return {rule: find_robust_response(result.scenario, result.outcome_matrix, rule) for rule in RULES}


def no_pick(scenario: Scenario) -> str:
    """Why a rule has no pick on *scenario*: every response marked not permitted, which leaves every rule without
    one (SPC-195), else every row at P 0, which leaves expected value without one."""
    return NO_PICK if permitted_responses(scenario) else NO_PICK_VETOED


def pick_words(scenario: Scenario, response: FriendlyResponse | None) -> str:
    """A pick as the page and the session log name it, or that there is none and why."""
    return no_pick(scenario).removeprefix("has ") if response is None else label(response)


def _tree_turn_one(result: ScenarioResult) -> dict[SelectorStrategy, TurnPick]:
    """Each rule's turn-1 pick over *result*'s tree as built, by select over its turns built in full; empty for one
    turn or a tree with no selection. The matrix pick passed to select is each rule's own, which only its lines read."""
    tree = result.tree
    if tree is None or tree.selection is None:
        return {}
    scenario, matrix = result.scenario, matrix_picks(result)
    picks: dict[SelectorStrategy, TurnPick] = {}
    for rule in RULES:
        pick = matrix[rule]
        own = None if pick is None else _index(scenario, pick)
        picks[rule] = select(scenario, tree.roots, tree.complete_turns, rule, matrix_pick=own).picks[0]
    return picks


def tree_turn_one_ties(result: ScenarioResult) -> dict[SelectorStrategy, tuple[FriendlyResponse, ...]]:
    """Each rule's turn-1 pick over *result*'s tree with every response tied with it, in the order entered (SPC-206),
    so rules that find the same tie agree whichever of it each picks; none for a rule with no pick, and empty for one
    turn or a tree with no selection."""
    scenario = result.scenario
    return {rule: tuple(scenario.friendly_responses[j] for j in first.choices)
            for rule, first in _tree_turn_one(result).items()}


def tree_turn_one_picks(result: ScenarioResult) -> dict[SelectorStrategy, FriendlyResponse | None]:
    """Each rule's turn-1 pick over *result*'s tree as built, the one with the lowest value, as select picks it; empty
    for one turn or a tree with no selection."""
    scenario = result.scenario
    return {rule: None if first.pick is None else scenario.friendly_responses[first.pick]
            for rule, first in _tree_turn_one(result).items()}


def matrix_ties(result: ScenarioResult) -> dict[SelectorStrategy, tuple[FriendlyResponse, ...]]:
    """Each rule's pick on *result*'s matrix with every response tied with it (SPC-206); none with no pick."""
    return {rule: tied_responses(result.scenario, result.outcome_matrix, rule) for rule in RULES}


def tie_words(tied: Sequence[FriendlyResponse]) -> str:
    """A tie as the page names it: "a tie between X (x1) and Y (y1)"."""
    return f"a tie between {named_list([label(r) for r in tied])}"


def _picked(tied: Sequence[FriendlyResponse]) -> str:
    """A pick as the page names it: the one response, or the tie."""
    return label(tied[0]) if len(tied) == 1 else tie_words(tied)


def expected_value_caveat(result: ScenarioResult) -> str | None:
    """The guidance the results show under expected value when its probability is not earned, whatever rule ran;
    None when it is earned. Read from a copy of *result* under expected value, so nothing on *result* changes."""
    return dataclasses.replace(result, robust_strategy=SelectorStrategy.EXPECTED_VALUE).objective_guidance


def compare_rules(result: ScenarioResult, primary: SelectorStrategy) -> RuleComparison:
    """Every rule's pick on *result*, whether they agree, and *primary*'s pick as the headline beside the chosen
    rule's; a tie under a rule is named wherever its pick is (SPC-206)."""
    scenario, matrix, ties = result.scenario, matrix_picks(result), matrix_ties(result)
    none = no_pick(scenario)
    picks = tuple(RulePick(rule, matrix[rule], none, ties[rule]) for rule in RULES)
    agree, groups = _grouped(scenario, [(rule, ties[rule]) for rule in RULES])
    tree = tree_turn_one_ties(result)
    tree_agree, tree_line = _tree_line(result, tree)
    tree_picks = tree_turn_one_picks(result)
    chosen = result.robust_strategy
    return RuleComparison(
        picks=picks, agree=agree, line=_agreement(scenario, agree, groups),
        tree_picks=tuple(tree_picks.items()), tree_line=tree_line,
        tree_agree=tree_agree, primary=primary, chosen=chosen, headline=matrix[primary],
        primary_line=_primary_line(primary, chosen, ties, none),
        star_line=_star_line(result, primary, ties), caveat=expected_value_caveat(result),
        stability=weight_stability(result, primary),
        chosen_stability=None if chosen is primary else weight_stability(
            result, chosen, subject=CHOSEN_SUBJECT.format(Rule=RULE_WORDS[chosen].capitalize())),
        tree_not_covered=TREE_NOT_COVERED if result.scenario.turns > 1 else None,
        collection=result.collection_under(primary), collection_rows=result.collection_rows_under(primary),
        headline_tied=ties[primary], tie_line=tie_line(primary, ties[primary]),
    )


def _agreement(scenario: Scenario, agree: bool, groups: str) -> str:
    """Whether the rules agree, in words; with every response marked not permitted, that no rule picks one."""
    if not permitted_responses(scenario):
        return NONE_PERMITTED
    return AGREE.format(pick=groups) if agree else DISAGREE.format(groups=groups)


def _index(scenario: Scenario, response: FriendlyResponse) -> int:
    """*response*'s place among the scenario's responses, by identity, so two rows alike stay apart."""
    return next(j for j, row in enumerate(scenario.friendly_responses) if row is response)


def label(response: FriendlyResponse) -> str:
    """A response as the page names it: its name, then its id in brackets."""
    return f"{response.name} ({response.id})"


def _grouped(
    scenario: Scenario, picks: Sequence[tuple[SelectorStrategy, tuple[FriendlyResponse, ...]]],
) -> tuple[bool, str]:
    """Whether every rule picks the same response, or finds the same tie (SPC-206), and the words: that pick when
    they agree, else each pick with the rules that make it, in RULES order, and any rule with no pick."""
    groups: dict[tuple[int, ...], list[str]] = {}
    for rule, tied in picks:
        groups.setdefault(tuple(_index(scenario, r) for r in tied), []).append(RULE_WORDS[rule])
    (only, *others) = groups
    if not others and only:
        return True, _picked([scenario.friendly_responses[j] for j in only])
    return False, "; ".join(_group(scenario, places, rules) for places, rules in groups.items())


def _group(scenario: Scenario, places: tuple[int, ...], rules: list[str]) -> str:
    named = " and ".join(rules)
    if not places:
        return f"{named} {NO_PICK}"
    verb = "pick" if len(rules) > 1 else "picks"
    return f"{named} {verb} {_picked([scenario.friendly_responses[j] for j in places])}"


def _tree_line(
    result: ScenarioResult, tree: dict[SelectorStrategy, tuple[FriendlyResponse, ...]],
) -> tuple[bool | None, str | None]:
    """Whether the rules agree on turn 1 of the tree, and that in words, naming the turns asked and, when the budget
    stopped it sooner, the turns built in full; (None, None) with no tree picks. With every response marked not
    permitted no rule picks, so the line says that and why, not that the rules disagree (SPC-195)."""
    if not tree or result.tree is None:
        return None, None
    built, asked = result.tree.complete_turns, result.scenario.turns
    words = {"turns": asked, "built": "" if built >= asked else TREE_BUILT.format(k=built)}
    if not permitted_responses(result.scenario):
        return False, TREE_NONE_PERMITTED.format(**words)
    agree, groups = _grouped(result.scenario, list(tree.items()))
    return agree, TREE_AGREE.format(**words, pick=groups) if agree else TREE_DISAGREE.format(**words, groups=groups)


def _its(tied: Sequence[FriendlyResponse], none: str) -> str:
    """What a rule picks, in the primary line's words; *none* says why it has no pick."""
    return f"it picks {_picked(tied)}" if tied else f"it {none}"


def _primary_line(
    primary: SelectorStrategy, chosen: SelectorStrategy, ties: dict[SelectorStrategy, tuple[FriendlyResponse, ...]],
    none: str,
) -> str:
    """The primary rule and its pick, and the chosen rule's beside it when they are not the same rule; *none* says
    why a rule has no pick. A tie names each tied response (SPC-206)."""
    pick = ties[primary]
    if chosen is primary:
        if not pick:
            return PRIMARY_CHOSEN_NONE.format(primary=RULE_WORDS[primary], none=none)
        return PRIMARY_CHOSEN.format(primary=RULE_WORDS[primary], pick=_picked(pick))
    return PRIMARY_DIFFERS.format(
        primary=RULE_WORDS[primary], said=_its(pick, none), chosen=RULE_WORDS[chosen],
        chosen_said=_its(ties[chosen], none), shown=SHOWN if pick else SHOWN_NONE,
    )


def _starred(tied: Sequence[FriendlyResponse]) -> str:
    """What the star marks: the one response, or each tied response, said to be tied (SPC-206)."""
    return label(tied[0]) if len(tied) == 1 else f"{named_list([label(r) for r in tied])}, tied"


def _star_line(
    result: ScenarioResult, primary: SelectorStrategy, ties: dict[SelectorStrategy, tuple[FriendlyResponse, ...]],
) -> str:
    """What the matrix's star and the ranking's highlights mark: the rule chosen's pick, or every response tied with
    it, said beside the primary's; nothing, with every response marked not permitted, or under expected value with
    every row at P 0."""
    chosen = result.robust_strategy
    if result.robust_best_response is None:
        return STAR_NO_WEIGHT.format(chosen=RULE_WORDS[chosen]) if permitted_responses(result.scenario) else STAR_NOTHING
    starred = _starred(result.tied_responses)
    if chosen is primary:
        return STAR_PRIMARY.format(pick=starred, chosen=RULE_WORDS[chosen])
    primary_pick = ties[primary]
    words = {"pick": starred, "chosen": RULE_WORDS[chosen], "primary": RULE_WORDS[primary]}
    if not primary_pick:
        return STAR_CHOSEN_NO_PRIMARY.format(**words)
    return STAR_CHOSEN.format(**words, primary_pick=_picked(primary_pick))
