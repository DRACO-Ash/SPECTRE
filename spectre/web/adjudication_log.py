"""The sweep's adjudication panel: the picture it holds, the form's record, and the coverage report (SPC-176).

The sweep holds what it showed for its red object as a Subject, the Threat
range, Understanding and ledger hash exactly as rendered. An analyst's
adjudication is recorded against that picture only: a form naming another
object or another ledger hash is refused as stale, so nobody records a
judgement of a range they were not shown, or against an object they were not
looking at. The object is checked as well as the hash because every object
with no held evidence rests on the same empty ledger. The bands come from the
held Subject, never the form.

Held per sign-in in the session state, like the Threat picture, the
interactions and every other operational record SPECTRE keeps. The database
holds accounts (users) and per-account training records (training_progress,
training_sessions, training_challenge_results, keyed on user_id), and that
training pattern was weighed and not taken: a training row scores the
account's own exercises, while an adjudication carries an operational
judgement, a catalogue number, the range shown and a free-text reason, and
no operational record is written to the database yet. The ledger its hash
names is not persisted either, so a stored entry would outlive the evidence
it points at. It would also still be per account, not pooled across
analysts. The cost of the session: one sign-in rarely reaches
MIN_FOR_COVERAGE, so the rate seldom shows until the owner approves a
persistent, pooled store. Recording changes no band and no assessment
(spectre.domain.adjudication).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from spectre.domain import threat_understanding as tu
from spectre.domain.adjudication import (
    MAX_REASON,
    Adjudication,
    Judgement,
    Subject,
    coverage_report,
    record,
)
from spectre.domain.provenance import ledger_input
from spectre.domain.threat_assessment import Band
from spectre.web.understanding_view import LEDGER_LABEL  # the hash the ledger shows, so the panel names the same one

NO_SUBJECT = "Not recorded: no Threat range is held to adjudicate. Run a sweep first."
STALE = ("Not recorded: this Threat range is no longer the one held. Run the sweep again and adjudicate what it "
         "shows.")
INCOMPLETE = ("Not recorded: choose agree or disagree for the Threat range and for Understanding, name what you judge "
              f"when you disagree, and give a reason of up to {MAX_REASON} characters.")
RECORDED = "Recorded. It changes no band: the Threat range and the verdict stand as assessed."
#: The newest adjudications the panel lists. Tuned, not sourced.
RECENT_SHOWN = 3
_DISAGREE = Judgement.DISAGREE.value


@dataclass(frozen=True)
class AdjudicationForm:
    """The adjudication form as posted, every field a string the route bounded."""

    ledger_hash: str
    satno: str
    on_range: str
    analyst_threat: str
    on_understanding: str
    analyst_understanding: str
    reason: str


def hold_subject(state: Any, name: str, satno: str | None, understanding: tu.ThreatUnderstanding | None,
                 now: datetime) -> None:
    """Hold what the sweep just showed for adjudication; a sweep with no Understanding or no number holds nothing."""
    if understanding is None or not satno:
        state.adjudication_subject = None
        return
    span = understanding.range
    state.adjudication_subject = Subject(
        satno=satno, name=name, floor=span.floor, ceiling=span.ceiling,
        understanding=understanding.understanding.level,
        ledger_hash=ledger_input(LEDGER_LABEL, span.ledger).sha256, assessed_at=now,
    )


def _band(name: str) -> Band | None:
    return Band[name] if name else None


def _level(name: str) -> tu.Understanding | None:
    return tu.Understanding[name] if name else None


def _entry(subject: Subject, form: AdjudicationForm, analyst: str, now: datetime) -> Adjudication | None:
    """The adjudication the form describes, or None when it is incomplete; a choice made under agree is ignored."""
    try:
        return Adjudication(
            subject=subject, on_range=Judgement(form.on_range), on_understanding=Judgement(form.on_understanding),
            reason=form.reason, analyst=analyst, recorded_at=now,
            analyst_threat=_band(form.analyst_threat) if form.on_range == _DISAGREE else None,
            analyst_understanding=(_level(form.analyst_understanding)
                                   if form.on_understanding == _DISAGREE else None),
        )
    except (ValueError, KeyError):
        return None


def take(state: Any, form: AdjudicationForm, analyst: str, now: datetime) -> tuple[Adjudication | None, str]:
    """Record the form against the held picture: the entry recorded, or None, and what the panel says."""
    subject = state.adjudication_subject
    if not isinstance(subject, Subject):
        return None, NO_SUBJECT
    # Both, because objects with no held evidence share one ledger, so the hash alone cannot tell them apart.
    if (form.satno, form.ledger_hash) != (subject.satno, subject.ledger_hash):
        return None, STALE
    entry = _entry(subject, form, analyst, now)
    if entry is None:
        return None, INCOMPLETE
    state.adjudications = record(state.adjudications, entry)
    return entry, RECORDED


def sweep_panel(state: Any) -> dict[str, Any] | None:
    """The panel under the sweep's Threat Understanding, or None when the sweep held no picture to adjudicate."""
    return view(state) if isinstance(state.adjudication_subject, Subject) else None


def view(state: Any, message: str = "") -> dict[str, Any]:
    """The panel: the held picture and the form for it, the coverage report and the newest entries."""
    subject = state.adjudication_subject
    held = subject if isinstance(subject, Subject) else None
    log = state.adjudications
    return {
        "subject": held is not None,
        "range_text": held.range_text if held else "",
        "understanding_text": f"Understanding {held.understanding.name}" if held else "",
        "ledger_hash": held.ledger_hash if held else "",
        "satno": held.satno if held else "",
        "bands": [b.name for b in Band],
        "levels": [u.name for u in tu.Understanding if held and u is not held.understanding],
        "report": coverage_report(log).sentence,
        "recent": [e.summary for e in reversed(log[-RECENT_SHOWN:])],
        "message": message,
        "max_reason": MAX_REASON,
    }
