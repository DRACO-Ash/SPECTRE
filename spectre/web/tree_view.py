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

The tree is also drawn (SPC-190): diagram lays it out left to right, a column per turn and each branch a box beside its
children, and the template writes it as SVG beside the plain branches, which stay its text alternative. Each box shows
its branch's heading and DIAGRAM_FIGURES, written as the branch writes them, so the drawing cannot say otherwise.
static/js/tree_diagram.js lays it out again, the same way, when a branch is collapsed, and zooms it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from spectre.domain.custody import span_text
from spectre.domain.decision import (
    MAX_TURNS,
    REMAINDER_LABEL,
    TERMS_INDEPENDENT_LINE,
    ScenarioResult,
    SelectorStrategy,
)
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
#: The figures each drawn box shows, of FIGURE_LABELS (SPC-190): the sequence's score and closest approach along it.
DIAGRAM_FIGURES = (FIGURE_LABELS[6], FIGURE_LABELS[3])
PLAN_MARK = "On the plan {rule} recommends"
#: What a drawn box says of its place (SPC-190): on the plan, with the plan's star, a best continuation, a response
#: marked not permitted, and a branch after one. The list below names the rule; the drawing does not repeat it.
_DRAWN_PLAN = "\u2605 On the plan"
_DRAWN_CONTINUATION = "Best continuation, not on the plan"
_DRAWN_NOT_PERMITTED = "Not permitted"
_DRAWN_FOLLOWS = "Excluded: it follows a response not permitted"
_COLLAPSE = "Collapse the branches after {heading}"
_EXPAND = "Open the branches after {heading}"
#: The drawing's geometry in its own units (SPC-190): a character's width at its 10-unit monospace text, a box's
#: padding, a line's height, the gaps between columns and between rows, and the margin. A box is as wide as its
#: longest line and tall enough for five: its heading, the remainder's caveat where red's move is the remainder of P,
#: two figures and its mark.
_CHAR_W = 6.0
_PAD = 8.0
_LINE_H = 13.0
_LINES = 5
_COL_GAP = 40.0
_ROW_GAP = 10.0
_MARGIN = 10.0
#: The radius of a box's control, in the drawing's units.
_TOGGLE_R = 7.0
#: Beside the best branch under a response the rule does not pick (SPC-189, design D14): in words of its own, never
#: the plan's, and with no star.
CONTINUATION_MARK = (
    "Best continuation under {rule} after {response} in turn {k}, which {rule} does not pick there; not on the plan"
)
HEADING = "Game tree: {turns} turns"
HEADING_NOT_BUILT = "Game tree: {turns} turns asked for, none built"
UPDATE_HEADING = "The update after turn 1"
#: Beside the tree (SPC-220, evaluation F-21): the engine looks at most MAX_TURNS turns ahead, and the branches of the
#: last turn shown, the deepest built in full, are valued as if no one moves after it.
LEAVES_LINE = (
    "Each branch of the last turn shown, turn {turns} here and turn {most} at most, is valued as if no one moves "
    "after it: its figures run to the end of the span searched with neither red nor us burning again, so a move "
    "either side would make later is in no figure."
)
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

    @property
    def key(self) -> str:
        """This branch's key, its red move and our response turn by turn, "0.1-2.3": the drawing's and the list's."""
        return "-".join(f"{action}.{response}" for action, response in self.steps)


@dataclass(frozen=True)
class DiagramLine:
    """One line of text in a drawn box: what it is ("title", "remainder", "figure" or "mark"), its baseline and its
    words."""

    kind: str
    y:    float
    text: str


@dataclass(frozen=True)
class DiagramBox:
    """One branch drawn: its key and its parent's ("" for turn 1), where it sits, what it says, and its control."""

    key:            str
    parent:         str
    x:              float
    y:              float
    title:          str
    figures:        tuple[str, ...]
    #: "plan", "continuation", "not-permitted" or "": what mark says, for the box's outline.
    mark_kind:      str
    mark:           str
    lines:          tuple[DiagramLine, ...]
    #: The SVG path from its parent's right side to its own left side; "" for turn 1.
    edge:           str
    #: Whether branches follow it, so it carries a control to collapse them.
    toggle:         bool
    collapse_label: str
    expand_label:   str


@dataclass(frozen=True)
class TreeDiagram:
    """The tree drawn: its size, its geometry, which tree_diagram.js reads to lay it out again, and its boxes in the
    order the branches are listed."""

    width:     float
    height:    float
    margin:    float
    box_w:     float
    box_h:     float
    col_gap:   float
    row_gap:   float
    char_w:    float
    pad:       float
    boxes:     tuple[DiagramBox, ...]

    @property
    def col_pitch(self) -> float:
        return self.box_w + self.col_gap

    @property
    def row_pitch(self) -> float:
        return self.box_h + self.row_gap

    @property
    def toggle_at(self) -> str:
        """Where a box's control sits, as an SVG translation: just past its right side, where its branches leave."""
        return f"translate({self.box_w + _TOGGLE_R + 2:g} {self.box_h / 2:g})"


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
    #: The assumptions the tree's figures rest on, beside it when it is built: the last turn's branches valued as if
    #: no one moves after it (SPC-220), and the score's terms added with nothing joining them (SPC-219).
    assumptions:    tuple[str, ...] = ()
    #: The tree drawn (SPC-190); None when no branch was built.
    diagram:        TreeDiagram | None = None


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


def _mark(node: NodeView, vetoed: Sequence[bool]) -> tuple[str, str]:
    """What a drawn box says of its place, and its kind: not permitted first, as the list greys it, then the plan,
    then a best continuation."""
    if node.not_permitted:
        return "not-permitted", _DRAWN_NOT_PERMITTED if vetoed[node.steps[-1][1]] else _DRAWN_FOLLOWS
    if node.on_plan:
        return "plan", _DRAWN_PLAN
    if node.continuation:
        return "continuation", _DRAWN_CONTINUATION
    return "", ""


def _texts(node: NodeView, vetoed: Sequence[bool]) -> tuple[str, tuple[str, ...], str, str]:
    """A box's title, figures, mark kind and mark."""
    shown = {f.label: f"{f.label}: {f.value} ({f.kind})" for f in node.figures}
    return (node.heading, tuple(shown[label] for label in DIAGRAM_FIGURES), *_mark(node, vetoed))


def _lines(node: NodeView, figures: tuple[str, ...], mark: str) -> tuple[DiagramLine, ...]:
    """A box's lines: its heading, the caveat the list sets beside a remainder branch's heading (SPC-203), its
    figures and its mark."""
    words = [
        ("title", node.heading), *([("remainder", node.remainder)] if node.remainder else []),
        *(("figure", f) for f in figures), *([("mark", mark)] if mark else []),
    ]
    return tuple(DiagramLine(kind, _PAD + _LINE_H * (i + 1) - 3.0, text) for i, (kind, text) in enumerate(words))


def _edge(parent: tuple[float, float], child: tuple[float, float], box_w: float, box_h: float) -> str:
    x1, y1, x2, y2 = parent[0] + box_w, parent[1] + box_h / 2, child[0], child[1] + box_h / 2
    middle = (x1 + x2) / 2
    return f"M{x1:g} {y1:g} C{middle:g} {y1:g} {middle:g} {y2:g} {x2:g} {y2:g}"


def _order(nodes: Sequence[NodeView], parent: str = "") -> list[tuple[NodeView, str]]:
    """Every branch under *nodes* with its parent's key, in the order the branches are listed."""
    found: list[tuple[NodeView, str]] = []
    for node in nodes:
        found += [(node, parent), *_order(node.children, node.key)]
    return found


def _places(
    order: Sequence[tuple[NodeView, str]], row_pitch: float, col_pitch: float,
) -> dict[str, tuple[float, float]]:
    """Where each box sits: each leaf the next row in the listed order, each branch with branches after it midway
    between its first and last, read last to first so its branches are placed before it; each turn a column."""
    leaves = [node.key for node, _ in order if not node.children]
    ys = {key: _MARGIN + row * row_pitch for row, key in enumerate(leaves)}
    for node, _ in reversed(order):
        if node.children:
            ys[node.key] = (ys[node.children[0].key] + ys[node.children[-1].key]) / 2
    return {node.key: (_MARGIN + (node.turn - 1) * col_pitch, ys[node.key]) for node, _ in order}


def diagram(nodes: Sequence[NodeView], vetoed: Sequence[bool]) -> TreeDiagram | None:
    """The tree *nodes* drawn (SPC-190), with *vetoed* saying which responses are marked not permitted; None for no
    node. tree_diagram.js lays out the branches left showing the way _places does."""
    if not nodes:
        return None
    order = _order(nodes)
    texts = {node.key: _texts(node, vetoed) for node, _ in order}
    lines = {node.key: _lines(node, texts[node.key][1], texts[node.key][3]) for node, _ in order}
    longest = max(len(line.text) for box in lines.values() for line in box)
    box_w, box_h = float(round(longest * _CHAR_W + 2 * _PAD)), 2 * _PAD + _LINES * _LINE_H
    row_pitch, col_pitch = box_h + _ROW_GAP, box_w + _COL_GAP
    where = _places(order, row_pitch, col_pitch)
    boxes = []
    for node, parent in order:
        title, figures, mark_kind, mark = texts[node.key]
        x, y = where[node.key]
        boxes.append(DiagramBox(
            node.key, parent, x, y, title, figures, mark_kind, mark, lines[node.key],
            _edge(where[parent], (x, y), box_w, box_h) if parent else "", bool(node.children),
            _COLLAPSE.format(heading=title), _EXPAND.format(heading=title),
        ))
    rows = sum(not node.children for node, _ in order)
    turns = max(node.turn for node, _ in order)
    return TreeDiagram(
        2 * _MARGIN + (turns - 1) * col_pitch + box_w, 2 * _MARGIN + (rows - 1) * row_pitch + box_h,
        _MARGIN, box_w, box_h, _COL_GAP, _ROW_GAP, _CHAR_W, _PAD, tuple(boxes),
    )


def _assumptions(nodes: Sequence[NodeView], seeds: str | None = None) -> tuple[str, ...]:
    """The lines beside a tree built: its last turn shown, the deepest branch built in full where the tree was built
    in part, valued as if no one moves after it (SPC-220), the score's terms added with nothing joining them
    (SPC-219), and, with *seeds*, how its sampled turns are drawn and judged (ScenarioResult.tree_seed_line, SPC-224).
    None for a tree with no branch."""
    if not nodes:
        return ()
    deepest = max(node.turn for node, _ in _order(nodes))
    return (LEAVES_LINE.format(turns=deepest, most=MAX_TURNS), TERMS_INDEPENDENT_LINE, *([seeds] if seeds else []))


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
        _assumptions(nodes, result.tree_seed_line),
        diagram(nodes, [bool(f.not_permitted) for f in result.scenario.friendly_responses]),
    )
