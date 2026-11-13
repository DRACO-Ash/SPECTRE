"""The game tree as the results page shows it (SPC-142).

The tree is server-rendered as nested details and summary elements: D3 is not vendored here. This module turns a
result's GameTree into plain values the template prints without doing any sum: each node's figures and its
sequence's, each with its basis kind and rule, the path of red moves and our responses it rests on, and whether it
is on the plan the recommendation follows, or, under a response the rule does not pick, the best continuation from
it, marked in words of its own and never as the plan (SPC-189, design D14). Delta-V is converted to m/s here, at the
route boundary, and only here.
The per-turn recommendation and the update after turn 1 are the selection's own lines, in two parts; under a rule
that reads no probability the second part is headed as what each turn lets us see, since nothing is updated. A
branch whose own response is marked not permitted (SPC-195) says so, with the reason, beside its heading; a later
branch below it says that it follows that response, so every sequence such a response starts is shown as excluded.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from spectre.domain.custody import span_text
from spectre.domain.decision import REMAINDER_LABEL, ScenarioResult, SelectorStrategy
from spectre.domain.decision_figures import TcaUncertainty
from spectre.domain.decision_tree import GameNode, GameTree, PathFigures
from spectre.domain.provenance import FigureBasis
from spectre.domain.tree_selectors import OBSERVED_NO_PICK, TreeSelection, continuation, follows_picks
from spectre.web.format_units import format_m_s, to_m_s

_SECONDS_PER_HOUR = 3600.0

#: Each node's figures, in the order the page lists them.
FIGURE_LABELS = (
    "Closest approach from this turn on",
    "Time of that closest approach",
    "Our burn this turn",
    "Closest approach along the sequence",
    "Our burns along the sequence",
    "Custody along the sequence",
    "Sequence score",
)
PLAN_MARK = "On the plan {rule} recommends"
#: Beside the best branch under a response the rule does not pick (SPC-189, design D14): in words of its own, never
#: the plan's, and with no star.
CONTINUATION_MARK = (
    "Best continuation under {rule} after {response} in turn {k}, which {rule} does not pick there; not on the plan"
)
HEADING = "Game tree: {turns} turns"
HEADING_NOT_BUILT = "Game tree: {turns} turns asked for, none built"
UPDATE_HEADING = "The update after turn 1"
UPDATE_HEADING_NO_PROBABILITY = "What each turn lets us see"
_HEADING = "Turn {k} of {turns}: red {action}, our {response}"
#: Beside the heading of a branch whose red move is the remainder of P: the engine's, not the operator's (SPC-203).
REMAINDER_BESIDE = f"(red's move here is {REMAINDER_LABEL})"
#: A branch below one whose response is marked not permitted (SPC-195): its sequence is excluded too.
_FOLLOWS = "Excluded: it follows {response} in turn {k}, which is marked not permitted."
_PATH = "Rests on: {steps}."
_STEP = "{action} against {response} in turn {k}"
_SUMMARY = "score {score:.3f} ({score_kind}); closest approach along it {closest:.1f} km ({closest_kind})"
_BAND = "{p5:.1f} km at P5; P50 {p50:.1f} km, P95 {p95:.1f} km; known to within {hw:.2f} km"
_AFTER_EPOCH = "{h} h after the scenario epoch"
_AT_EDGE = "; at the edge of the search, not an encounter"
_NO_UNCERTAINTY = "; no uncertainty recorded"
# A turn-1 node carries its cell's time basis, which states the matrix's display; this view writes hours instead.
_TO_THE_MINUTE = " and shown to the minute"
_IN_HOURS = "; shown here in hours after the scenario epoch, no finer than its uncertainty allows. "
_NO_UNCERTAINTY_NOTE = "No uncertainty is recorded for this time."
_HELD = "held over the {h:g} h horizon"
_LOST = "lost for up to {gap:.1f} h of the {h:g} h horizon"
#: Custody degraded for some of the horizon (SPC-179), never shown as held or lost, and its hours never as lost.
_DEGRADED = "degraded, neither held nor lost, for {d} of the {h:g} h horizon"
_DEGRADED_THEN_LOST = "degraded, neither held nor lost, for {d}, then lost for up to {gap:.1f} h of the {h:g} h horizon"
_SCORE = "{score:.3f}, lower is better"


def custody_value(path: PathFigures, horizon_h: float) -> str:
    """A sequence's custody in words: held, lost for how long, or degraded for how long and then lost (SPC-179)."""
    if path.custody_maintained:
        return _HELD.format(h=horizon_h)
    degraded = getattr(path, "custody_degraded_hours", 0.0)
    if not degraded:
        return _LOST.format(gap=path.custody_gap_hours, h=horizon_h)
    if not path.custody_gap_hours:
        return _DEGRADED.format(d=span_text(degraded), h=horizon_h)
    return _DEGRADED_THEN_LOST.format(d=span_text(degraded), gap=path.custody_gap_hours, h=horizon_h)


@dataclass(frozen=True)
class FigureView:
    """One figure as shown: its label, its value in words and units, its basis kind and the rule behind it."""

    label: str
    value: str
    kind:  str
    note:  str


@dataclass(frozen=True)
class NodeView:
    """One branch as shown, with the branches below it."""

    turn:     int
    steps:    tuple[tuple[int, int], ...]   # (red's move, our response) per turn, this one last
    heading:  str
    path:     str
    summary:  str
    on_plan:  bool
    plan:     str
    figures:  tuple[FigureView, ...]
    children: tuple[NodeView, ...]
    #: "Not permitted:" and the reason when this branch's own response is marked so (SPC-195); else, when an earlier
    #: turn's response along its sequence is, that it follows that response; else empty.
    not_permitted: str = ""
    #: REMAINDER_BESIDE when this branch's red move is the remainder of P, the engine's row (SPC-203); else empty.
    remainder: str = ""
    #: CONTINUATION_MARK when this branch is the best continuation under a response the rule does not pick
    #: (SPC-189); else empty. Never set on a branch on the plan.
    continuation: str = ""


@dataclass(frozen=True)
class TreeView:
    """What the page shows of a tree: its heading, its lines, the deepest turn built in full when built in part, the
    rule's per-turn recommendation, the update after turn 1 (or, under a rule that reads no probability, what each
    turn lets us see) with its heading and basis, and the nodes."""

    heading:        str
    turns:          int
    complete_turns: int
    lines:          tuple[str, ...]
    deepest:        str | None
    rule:           str
    recommendation: tuple[str, ...]
    update_heading: str
    update:         tuple[str, ...]
    update_basis:   FigureView | None
    nodes:          tuple[NodeView, ...]


def _figure(label: str, value: str, basis: FigureBasis, extra: str = "") -> FigureView:
    return FigureView(label, value, basis.kind.value, basis.note + extra)


def _m_s(km_s: float) -> str:
    return f"{format_m_s(to_m_s(km_s))} m/s"


def _closest(node: GameNode) -> str:
    band, hw = node.figures.band, node.figures.half_width_km
    if band is None or hw is None:
        return f"{node.figures.closest_approach_km:.1f} km"
    return _BAND.format(p5=band[5], p50=band[50], p95=band[95], hw=hw)


def _when(tca: datetime, epoch: datetime, uncertainty: TcaUncertainty | None) -> str:
    """The TCA in hours after the scenario epoch, to no finer than its uncertainty allows, with that uncertainty."""
    h = (tca - epoch).total_seconds() / _SECONDS_PER_HOUR
    if uncertainty is None:
        return _AFTER_EPOCH.format(h=f"{h:.2f}") + _NO_UNCERTAINTY
    shown = _AFTER_EPOCH.format(h=uncertainty.hours(h))
    pm = uncertainty.pm
    if pm:
        return f"{shown}, {pm}"
    return shown + (_AT_EDGE if uncertainty.at_edge else _NO_UNCERTAINTY)


def _when_note(note: str, uncertainty: TcaUncertainty | None) -> str:
    """The time's basis as this view shows it: the engine's rule, how the hours are written, and what the
    uncertainty rests on, or that none is recorded."""
    return note.removesuffix(_TO_THE_MINUTE) + _IN_HOURS + (
        _NO_UNCERTAINTY_NOTE if uncertainty is None else uncertainty.title
    )


class _Builder:
    def __init__(self, result: ScenarioResult, tree: GameTree) -> None:
        self.result, self.tree = result, tree
        self.actions = [a.name for a in result.scenario.adversary_actions]
        # The remainder of P, red's move of no adversary action, is the engine's row, and beside its heading the branch
        # says so (SPC-203).
        self.beside = [REMAINDER_BESIDE if a.remainder else "" for a in result.scenario.adversary_actions]
        self.responses = [f.name for f in result.scenario.friendly_responses]
        self.vetoes = [f.not_permitted or "" for f in result.scenario.friendly_responses]

    def node(self, node: GameNode, before: Sequence[tuple[int, int]]) -> NodeView:
        steps = (*before, (node.action, node.response))
        path = ", then ".join(
            _STEP.format(action=self.actions[a], response=self.responses[r], k=k) for k, (a, r) in enumerate(steps, 1)
        )
        selection = self.tree.selection
        on = selection is not None and follows_picks(self.result.scenario, selection, steps)
        plan = PLAN_MARK.format(rule=selection.strategy.value.replace("_", " ")) if selection is not None and on else ""
        return NodeView(
            node.turn, steps,
            _HEADING.format(
                k=node.turn, turns=self.tree.turns, action=self.actions[node.action],
                response=self.responses[node.response],
            ),
            _PATH.format(steps=path),
            _SUMMARY.format(
                score=node.path.score, score_kind=node.path.bases.score.kind.value,
                closest=node.path.closest_approach_km, closest_kind=node.path.bases.closest_approach_km.kind.value,
            ),
            on, plan, self.figures(node),
            tuple(self.node(child, steps) for child in node.children),
            self.vetoes[node.response] or self.follows(before), self.beside[node.action], self.best(steps),
        )

    def best(self, steps: Sequence[tuple[int, int]]) -> str:
        """CONTINUATION_MARK when *steps* is the best continuation under a response the rule does not pick, naming
        that response and its turn; else empty (SPC-189)."""
        selection = self.tree.selection
        turn = None if selection is None else continuation(self.result.scenario, selection, steps)
        if selection is None or turn is None:
            return ""
        rule = selection.strategy.value.replace("_", " ")
        return CONTINUATION_MARK.format(rule=rule, response=self.responses[steps[turn - 1][1]], k=turn)

    def follows(self, before: Sequence[tuple[int, int]]) -> str:
        """That a branch follows a response marked not permitted in an earlier turn, the first such; else empty."""
        return next(
            (_FOLLOWS.format(response=self.responses[r], k=k) for k, (_, r) in enumerate(before, 1) if self.vetoes[r]),
            "",
        )

    def figures(self, node: GameNode) -> tuple[FigureView, ...]:
        bases, path = node.figures.bases, node.path
        horizon = self.result.scenario.horizon_hours
        maintained, gap = path.custody_bases
        custody = custody_value(path, horizon)
        tca = node.figures.tca_uncertainty
        when = _when(node.figures.tca_utc, self.result.scenario.epoch_utc, tca)
        timed = FigureBasis(bases.time_to_closest_hours.kind, _when_note(bases.time_to_closest_hours.note, tca))
        values = (
            (_closest(node), bases.closest_approach_km, ""),
            (when, timed, ""),
            (_m_s(node.figures.delta_v_km_s), bases.delta_v_cost_km_s, ""),
            (f"{path.closest_approach_km:.1f} km", path.bases.closest_approach_km, ""),
            (_m_s(path.delta_v_km_s), path.bases.delta_v_km_s, ""),
            (custody, maintained, f". The hours lost: {gap.note}"),
            (_SCORE.format(score=path.score), path.bases.score, ""),
        )
        return tuple(
            _figure(label, value, basis, extra)
            for label, (value, basis, extra) in zip(FIGURE_LABELS, values, strict=True)
        )


def _update(result: ScenarioResult, selection: TreeSelection | None) -> tuple[str, ...]:
    """The selection's update lines; with no pick, that a stated observation updated nothing, else nothing."""
    if selection is not None:
        return selection.update
    observed = result.scenario.observed
    return () if observed is None else (OBSERVED_NO_PICK.format(seen=observed.value),)


def tree_view(result: ScenarioResult) -> TreeView | None:
    """The tree of *result* as the page shows it; None for one turn, which has no tree."""
    tree = result.tree
    if tree is None:
        return None
    selection = tree.selection
    builder = _Builder(result, tree)
    stated = None if selection is None else selection.stated
    nodes = tuple(builder.node(root, ()) for root in tree.roots)
    reads_p = selection is None or selection.strategy is SelectorStrategy.EXPECTED_VALUE
    return TreeView(
        (HEADING if nodes else HEADING_NOT_BUILT).format(turns=tree.turns),
        tree.turns, tree.complete_turns, tree.lines, tree.deepest, result.robust_strategy.value.replace("_", " "),
        () if selection is None else selection.recommendation,
        UPDATE_HEADING if reads_p else UPDATE_HEADING_NO_PROBABILITY,
        _update(result, selection),
        None if stated is None else FigureView(UPDATE_HEADING, stated.line, stated.basis.kind.value, stated.basis.note),
        nodes,
    )
