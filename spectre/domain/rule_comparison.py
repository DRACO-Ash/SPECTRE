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
  is never counted as agreeing with another rule. find_robust_response would still name the first response there.

Nothing here changes a figure, a pick or the rule the evaluation ran under: every pick is read from the result.
Imports the Decision Engine and its tree selectors, never the reverse; nothing here imports the web layer.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from dataclasses import dataclass

from spectre.domain.decision import FriendlyResponse, Scenario, ScenarioResult, SelectorStrategy, find_robust_response
from spectre.domain.tree_selectors import select

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
#: A tree the budget stopped before its last turn: its picks rest on the turns built in full.
TREE_BUILT = ", built in full to turn {k} only"
#: Why a rule has no pick: only expected value can have none, when every row has P 0.
NO_PICK = "has no pick, since every row has P 0"
PRIMARY_CHOSEN = "This deployment's primary rule is {primary}, the rule chosen: the recommendation is its pick, {pick}."
PRIMARY_CHOSEN_NONE = (
    "This deployment's primary rule is {primary}, the rule chosen: it " + NO_PICK + ", so no recommendation is shown."
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
STAR_NONE = (
    "\u2605 and the blue highlights mark {pick} only as the first response: {chosen}, the rule chosen, " + NO_PICK + "."
)


@dataclass(frozen=True)
class RulePick:
    """One rule's pick on the one-turn matrix, None for none, with the rule in words and its meaning."""

    rule:     SelectorStrategy
    response: FriendlyResponse | None

    @property
    def words(self) -> str:
        return RULE_WORDS[self.rule]

    @property
    def meaning(self) -> str:
        return MEANINGS[self.rule]

    @property
    def pick_text(self) -> str:
        """The pick as the page names it, or that the rule has none and why."""
        return "no pick, since every row has P 0" if self.response is None else label(self.response)


@dataclass(frozen=True)
class RuleComparison:
    """Every rule's pick on a result, whether they agree, and the primary rule's pick as the headline.

    *picks* are the one-turn matrix's, in RULES order; *tree_picks* each rule's turn-1 pick over the tree, None for a
    rule with no pick, and empty for one turn or a tree with no turn built; *tree_agree* None then. *headline* is None
    when the primary rule has no pick. *star_line* says what the matrix's star marks. *caveat* is the guidance the
    results give when expected value's probability is not earned, whatever rule ran; None when it is earned.
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
    basis:        str = PICKS_BASIS

    @property
    def differs(self) -> bool:
        """Whether the rule the evaluation ran under is not the deployment's primary rule."""
        return self.chosen is not self.primary


def matrix_picks(result: ScenarioResult) -> dict[SelectorStrategy, FriendlyResponse | None]:
    """Each rule's pick on *result*'s matrix, by find_robust_response; nothing on *result* is changed.

    Expected value has none when every row has P 0, as on the tree (tree_selectors): find_robust_response would name
    the first response there, a tie it has not earned.
    """
    return {
        rule: None if rule is SelectorStrategy.EXPECTED_VALUE and not _weighted(result.scenario)
        else find_robust_response(result.scenario, result.outcome_matrix, rule)
        for rule in RULES
    }


def _weighted(scenario: Scenario) -> bool:
    """Whether any row's P is above 0, so expected value has a weight to pick on."""
    return sum(action.probability for action in scenario.adversary_actions) > 0.0


def tree_turn_one_picks(result: ScenarioResult) -> dict[SelectorStrategy, FriendlyResponse | None]:
    """Each rule's turn-1 pick over *result*'s tree as built, by select over its turns built in full; empty for one
    turn or a tree with no selection. The matrix pick passed to select is each rule's own, which only its lines read."""
    tree = result.tree
    if tree is None or tree.selection is None:
        return {}
    scenario, matrix = result.scenario, matrix_picks(result)
    picks: dict[SelectorStrategy, FriendlyResponse | None] = {}
    for rule in RULES:
        own = _index(scenario, matrix[rule] or scenario.friendly_responses[0])
        first = select(scenario, tree.roots, tree.complete_turns, rule, matrix_pick=own).picks[0].pick
        picks[rule] = None if first is None else scenario.friendly_responses[first]
    return picks


def expected_value_caveat(result: ScenarioResult) -> str | None:
    """The guidance the results show under expected value when its probability is not earned, whatever rule ran;
    None when it is earned. Read from a copy of *result* under expected value, so nothing on *result* changes."""
    return dataclasses.replace(result, robust_strategy=SelectorStrategy.EXPECTED_VALUE).objective_guidance


def compare_rules(result: ScenarioResult, primary: SelectorStrategy) -> RuleComparison:
    """Every rule's pick on *result*, whether they agree, and *primary*'s pick as the headline beside the chosen
    rule's."""
    scenario, matrix = result.scenario, matrix_picks(result)
    picks = tuple(RulePick(rule, matrix[rule]) for rule in RULES)
    agree, groups = _grouped(scenario, [(p.rule, p.response) for p in picks])
    tree = tree_turn_one_picks(result)
    tree_agree, tree_line = _tree_line(result, tree)
    chosen = result.robust_strategy
    return RuleComparison(
        picks=picks, agree=agree,
        line=AGREE.format(pick=groups) if agree else DISAGREE.format(groups=groups),
        tree_picks=tuple(tree.items()), tree_line=tree_line, tree_agree=tree_agree,
        primary=primary, chosen=chosen, headline=matrix[primary],
        primary_line=_primary_line(primary, chosen, matrix),
        star_line=_star_line(result, primary, matrix), caveat=expected_value_caveat(result),
    )


def _index(scenario: Scenario, response: FriendlyResponse) -> int:
    """*response*'s place among the scenario's responses, by identity, so two rows alike stay apart."""
    return next(j for j, row in enumerate(scenario.friendly_responses) if row is response)


def label(response: FriendlyResponse) -> str:
    """A response as the page names it: its name, then its id in brackets."""
    return f"{response.name} ({response.id})"


def _grouped(
    scenario: Scenario, picks: Sequence[tuple[SelectorStrategy, FriendlyResponse | None]],
) -> tuple[bool, str]:
    """Whether every rule picks the same response, and the words: that response when they agree, else each response
    with the rules that pick it, in RULES order, and any rule with no pick."""
    groups: dict[int | None, list[str]] = {}
    for rule, response in picks:
        groups.setdefault(None if response is None else _index(scenario, response), []).append(RULE_WORDS[rule])
    (only, *others) = groups
    if not others and only is not None:
        return True, label(scenario.friendly_responses[only])
    return False, "; ".join(_group(scenario, place, rules) for place, rules in groups.items())


def _group(scenario: Scenario, place: int | None, rules: list[str]) -> str:
    named = " and ".join(rules)
    if place is None:
        return f"{named} {NO_PICK}"
    verb = "pick" if len(rules) > 1 else "picks"
    return f"{named} {verb} {label(scenario.friendly_responses[place])}"


def _tree_line(
    result: ScenarioResult, tree: dict[SelectorStrategy, FriendlyResponse | None],
) -> tuple[bool | None, str | None]:
    """Whether the rules agree on turn 1 of the tree, and that in words, naming the turns asked and, when the budget
    stopped it sooner, the turns built in full; (None, None) with no tree picks."""
    if not tree or result.tree is None:
        return None, None
    agree, groups = _grouped(result.scenario, list(tree.items()))
    built, asked = result.tree.complete_turns, result.scenario.turns
    words = {"turns": asked, "built": "" if built >= asked else TREE_BUILT.format(k=built)}
    return agree, TREE_AGREE.format(**words, pick=groups) if agree else TREE_DISAGREE.format(**words, groups=groups)


def _its(response: FriendlyResponse | None) -> str:
    """What a rule picks, in the primary line's words."""
    return f"it {NO_PICK}" if response is None else f"it picks {label(response)}"


def _primary_line(
    primary: SelectorStrategy, chosen: SelectorStrategy, matrix: dict[SelectorStrategy, FriendlyResponse | None],
) -> str:
    """The primary rule and its pick, and the chosen rule's beside it when they are not the same rule."""
    pick = matrix[primary]
    if chosen is primary:
        if pick is None:
            return PRIMARY_CHOSEN_NONE.format(primary=RULE_WORDS[primary])
        return PRIMARY_CHOSEN.format(primary=RULE_WORDS[primary], pick=label(pick))
    return PRIMARY_DIFFERS.format(
        primary=RULE_WORDS[primary], said=_its(pick), chosen=RULE_WORDS[chosen], chosen_said=_its(matrix[chosen]),
        shown=SHOWN_NONE if pick is None else SHOWN,
    )


def _star_line(
    result: ScenarioResult, primary: SelectorStrategy, matrix: dict[SelectorStrategy, FriendlyResponse | None],
) -> str:
    """What the matrix's star and the ranking's highlights mark: the rule chosen's pick, said beside the primary's."""
    chosen, starred = result.robust_strategy, label(result.robust_best_response)
    if matrix[chosen] is None:
        return STAR_NONE.format(pick=starred, chosen=RULE_WORDS[chosen])
    if chosen is primary:
        return STAR_PRIMARY.format(pick=starred, chosen=RULE_WORDS[chosen])
    primary_pick = matrix[primary]
    words = {"pick": starred, "chosen": RULE_WORDS[chosen], "primary": RULE_WORDS[primary]}
    if primary_pick is None:
        return STAR_CHOSEN_NO_PRIMARY.format(**words)
    return STAR_CHOSEN.format(**words, primary_pick=label(primary_pick))
