"""Threat Understanding as the operator reads it, one builder for every panel (SPC-168).

The sweep, the target intel card and the Pattern of Life panel read one
object through these functions, so the understanding strip for that object
is the same wherever it is shown (concept section 6.4 and 7.3). What an
object holds is gathered by the caller from what SPECTRE already has, the
intel record, the GCAT cache and the held history, and nothing here fetches.

Every band on screen is labelled "Threat" or "Understanding", the two never
share a sentence, and no percentage is written (I13). A failure is logged
and reads as no understanding, so the panel stands without it; the detail
never reaches the page.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from spectre.domain import threat_understanding as tu
from spectre.domain.custody import Custody, age_text
from spectre.domain.interaction_graph import Edge, MissEdge, SeedPath
from spectre.domain.provenance import ledger_input
from spectre.domain.threat_assessment import Band
from spectre.web.elsets import limit_hours_for_regime
from spectre.web.format_units import format_tof_label
from spectre.web.log_safety import log_safe

logger = logging.getLogger(__name__)

#: The understanding strip's four cells, in the operator's words: Behaviour is how it manoeuvres.
STRIP_NAMES: dict[tu.Dimension, str] = {
    tu.Dimension.IDENTITY: "Identity", tu.Dimension.CAPABILITY: "Capability",
    tu.Dimension.BEHAVIOUR: "Manoeuvres", tu.Dimension.INTERACTIONS: "Interactions",
}
_STRIP_FILL: dict[tu.Depth, str] = {tu.Depth.EARNED: "full", tu.Depth.PARTIAL: "half", tu.Depth.NONE: "empty"}
LEDGER_LABEL = "threat understanding ledger"
#: How many cues the Understanding line names (section 6.3).
CUES_SHOWN = 3
#: The Threat line on a panel with no intercept in view: there is no ACCESS to bound a range by.
_NO_INTERCEPT = "Threat: not assessed on this panel. The sweep bounds it by an intercept's access."
_RECORD_ROOT = "intel-record:"


@dataclass(frozen=True)
class HeldObject:
    """What SPECTRE holds about one object, read without a new fetch.

    *catalogue* is its GCAT row and the cache's refresh time; *signals* its
    held history, read once. *custody* is judged by the panel's own rule and
    sets volatility; "no burns" is judged on the history's own window instead,
    so the strip does not depend on which element set the panel reads.
    *interactions* are the approaches attributed to a burn of its own: the
    warning changes a sweep flew (SPC-172) and the close approaches it judged
    (SPC-173), held per object in the session so every panel reads the same.
    *notes* are what the ledger states about them: each refusal, the probe
    grade of a UDL conjunction and whether a hostile seed list is configured.
    *seed_paths* lead from it to hostile seeds through the edges the session
    holds for every object (SPC-174).
    """

    satno: str
    record: Mapping[str, Any] | None
    catalogue: tuple[Mapping[str, str], datetime] | None
    signals: tu.HistorySignals | None
    custody: Custody
    interactions: tuple[Edge | MissEdge, ...] = ()
    notes: tuple[str, ...] = ()
    seed_paths: tuple[SeedPath, ...] = ()

    def items(self, now: datetime, regime: str, access_dv_m_s: float = math.inf) -> tuple[tu.EvidenceItem, ...]:
        """The evidence items. With no intercept in view, "no burns" is judged against any burn the floor resolves.

        Custody across the history's window is judged at *now* against the
        element-set limit of *regime* (section 5.3), the same on every panel.
        """
        signals = self.signals
        judged = tuple(tu.HeldBurn(b.epoch, b.normality) for b in (signals.burns if signals is not None else ()))
        return (
            *tu.intel_items(self.record, self.satno),
            *(tu.gcat_items(self.catalogue[0], self.catalogue[1], self.satno) if self.catalogue is not None else ()),
            *(tu.history_items(signals, access_delta_v_m_s=access_dv_m_s,
                               custody=tu.window_custody(signals, now, limit_hours_for_regime(regime)))
              if signals is not None else ()),
            *tu.interaction_items(self.interactions, judged=judged, hours=format_tof_label),
            *tu.propagation_items(self.seed_paths, now, judged=judged, hours=format_tof_label),
        )

    def situate(self, situation: tu.Situation) -> tu.Situation:
        """*situation* with what the history and the intel record add to it."""
        return tu.with_record(tu.with_history(situation, self.signals), self.record)


def object_understanding(held: HeldObject, now: datetime, *, regime: str,
                         data_mode: str | None) -> tu.ThreatUnderstanding | None:
    """The object's understanding with no intercept in view, or None, logged, when it cannot be read.

    ACCESS is left at CRITICAL, the ceiling no geometry has lowered, so the
    view built from it quotes no Threat steps (``understanding_view`` with
    *intercept* False); the strip does not depend on it.
    """
    try:
        situation = tu.Situation(now=now, access=Band.CRITICAL, custody=held.custody, history_truncated=False,
                                 regime=regime, elset_limit_hours=limit_hours_for_regime(regime), data_mode=data_mode)
        return tu.assess(held.items(now, regime), held.situate(situation), with_cues=True)
    # BLE001: the understanding must never take its panel down with it.
    except Exception as exc:  # noqa: BLE001
        logger.warning("Threat Understanding failed for %s: %s", log_safe(held.satno), log_safe(exc))
        return None


def _age(row: tu.LedgerRow) -> str:
    return "undated" if row.age_days is None else age_text(row.age_days * 24.0)


def ledger_view(row: tu.LedgerRow) -> dict[str, str]:
    """One row of "What it rests on", every figure as the operator reads it.

    The note says what the item is ("declared, not observed") before what
    became of it, so a declaration never reads as an observation.
    """
    return {
        "dimension": STRIP_NAMES[row.item.dimension], "claim": row.item.label,
        "reading": tu.reading_text(row.item), "grade": row.item.grade, "age": _age(row),
        "basis": row.item.basis.value, "q": f"{row.q:.2f}", "status": row.status.value,
        "note": "; ".join(note for note in (row.item.note, row.note) if note),
    }


def _strip(span: tu.ThreatRange) -> list[dict[str, str]]:
    strip = []
    for dimension, name in STRIP_NAMES.items():
        depth = tu.depth(span.coverage[dimension])
        held = [f"{r.item.label}: {r.item.grade}, {_age(r)}, {r.item.basis.value}"
                for r in span.ledger if r.item.dimension is dimension]
        strip.append({"name": name, "depth": depth.value, "fill": _STRIP_FILL[depth], "detail": "; ".join(held)})
    return strip


def _cues(understanding: tu.ThreatUnderstanding, *, intercept: bool) -> list[str]:
    """The cues the operator can act on, best first: only fed ones, and no more than section 6.3's three."""
    return [tu.cue_text(c, threat=intercept) for c in understanding.cues if c.fed][:CUES_SHOWN]


def _record(understanding: tu.ThreatUnderstanding, *, intercept: bool) -> tuple[str, str]:
    """Section 7.3: the intel record's grade and what it does, and the cue to date and source it."""
    row = next((r for r in understanding.range.ledger if r.item.derived_from.startswith(_RECORD_ROOT)
                and r.item.dimension is tu.Dimension.IDENTITY), None)
    if row is None:
        return "", ""
    what = f"sets the {tu.reading_text(row.item)}" if row.applied else "listed, does not move the Threat range"
    record = f"This record: {row.item.note or 'dated and sourced'} [{row.item.grade}]: {what}"
    cue = next((tu.cue_text(c, threat=intercept) for c in understanding.cues if c.record), "")
    return record, cue


def understanding_view(understanding: tu.ThreatUnderstanding, *, intercept: bool = True,
                       notes: Sequence[str] = ()) -> dict[str, Any]:
    """Section 6.4: the Threat line, the Understanding line and its cues, the strip, the ledger and what is missing.

    *intercept* is whether an intercept is in view: without one there is no
    ACCESS, so the Threat line says where the threat is assessed instead,
    and the cues name what they would firm up rather than Threat steps.
    *notes* are what the ledger states beside its rows (SPC-173, SPC-174).
    """
    span = understanding.range
    record, record_cue = _record(understanding, intercept=intercept)
    return {
        "threat": tu.threat_sentence(understanding) if intercept else _NO_INTERCEPT,
        "band": understanding.verdict.band.name.lower() if intercept else "unknown",
        "understanding": understanding.understanding.statement,
        "outline": understanding.understanding.level is tu.Understanding.LOW,
        "cues": _cues(understanding, intercept=intercept),
        "strip": _strip(span),
        "ledger": [ledger_view(r) for r in span.ledger],
        "ledger_hash": ledger_input(LEDGER_LABEL, span.ledger).sha256,
        "ledger_notes": list(notes),
        "missing": list(tu.missing(span)),
        "record": record,
        "record_cue": record_cue,
        "heading": "EVIDENCE BEHIND THE VERDICT, IN SHADOW" if intercept else "WHAT IS UNDERSTOOD ABOUT THIS OBJECT",
        "note": "Shown beside the verdict above for comparison. It does not change that verdict." if intercept else "",
    }


def object_view(held: HeldObject, now: datetime, *, regime: str, data_mode: str | None) -> dict[str, Any] | None:
    """The view of an object with no intercept in view, or None when its understanding could not be read."""
    understanding = object_understanding(held, now, regime=regime, data_mode=data_mode)
    return None if understanding is None else understanding_view(understanding, intercept=False, notes=held.notes)
