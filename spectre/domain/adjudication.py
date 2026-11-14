"""The adjudication log and the coverage report (SPC-176, Threat Understanding concept section 7.6).

An analyst who has read the sweep's Threat range and Understanding for an
object records whether they agree, and if not what they judge instead, with
a reason. The record keeps the range, Understanding and ledger hash exactly
as they were shown, so it says what the analyst was looking at.

An override never moves a band (section 8: no feedback that moves a band).
Nothing here returns a Band or touches an assessment: the log is read only
to measure the model. The coverage rate is how often the earned Threat range
held the analyst's judgement, an agreement or a judged Threat inside
[floor, ceiling]. It is computed only once MIN_FOR_COVERAGE adjudications
exist, because a rate over a handful says nothing it has earned, and it is
written as a count, "27 of 30", never a percentage (section 8).

Pure: no I/O, no clock, no framework. The web layer holds the log.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from spectre.domain.threat_assessment import Band
from spectre.domain.threat_understanding import Understanding

__all__ = [
    "MAX_HELD",
    "MAX_REASON",
    "MIN_FOR_COVERAGE",
    "Adjudication",
    "CoverageReport",
    "Judgement",
    "Subject",
    "coverage_report",
    "record",
]

#: Adjudications needed before a coverage rate is computed (concept section 10, SPC-176). Tuned, not sourced.
MIN_FOR_COVERAGE: int = 30
#: The most adjudications one log holds, the newest kept, so a log cannot grow without bound. Tuned, not sourced.
MAX_HELD: int = 1000
#: The longest reason held, in characters, after it is put on one line. Tuned, not sourced.
MAX_REASON: int = 500

_LEDGER_HASH = re.compile(r"[0-9a-f]{64}")


class Judgement(Enum):
    """What the analyst made of what was shown."""

    AGREE = "agree"
    DISAGREE = "disagree"


@dataclass(frozen=True)
class Subject:
    """The Threat range and Understanding an analyst adjudicates, exactly as the sweep showed them.

    *ledger_hash* is the sha256 of the ledger the range rests on (SPC-166), so
    the record names the evidence as well as the bands.
    """

    satno: str
    name: str
    floor: Band
    ceiling: Band
    understanding: Understanding
    ledger_hash: str
    assessed_at: datetime

    def __post_init__(self) -> None:
        if self.floor > self.ceiling:
            raise ValueError("a Threat range with its floor above its ceiling")
        if not _LEDGER_HASH.fullmatch(self.ledger_hash):
            raise ValueError("a subject is named by the ledger hash it rests on: 64 lower-case hex characters")

    @property
    def range_text(self) -> str:
        span = self.floor.name if self.floor == self.ceiling else f"{self.floor.name} to {self.ceiling.name}"
        return f"Threat range {span}"


def _one_line(reason: str) -> str:
    printable = "".join(c if c.isprintable() else " " for c in reason)
    return " ".join(printable.split())


@dataclass(frozen=True)
class Adjudication:
    """One analyst's judgement of one Subject, with the reason.

    Disagreeing with the range names the Threat band the analyst judges;
    disagreeing with Understanding names the level they judge, which must
    differ from the one shown. Agreeing names neither. The reason is held on
    one line, at most MAX_REASON characters.
    """

    subject: Subject
    on_range: Judgement
    on_understanding: Judgement
    reason: str
    analyst: str
    recorded_at: datetime
    analyst_threat: Band | None = None
    analyst_understanding: Understanding | None = None

    def __post_init__(self) -> None:
        reason = _one_line(self.reason)
        if not reason or len(reason) > MAX_REASON:
            raise ValueError(f"an adjudication needs a reason of 1 to {MAX_REASON} characters")
        object.__setattr__(self, "reason", reason)
        self._check_range()
        self._check_understanding()

    def _check_range(self) -> None:
        if self.on_range is Judgement.DISAGREE and self.analyst_threat is None:
            raise ValueError("disagreeing with the Threat range names the Threat the analyst judges")
        if self.on_range is Judgement.AGREE and self.analyst_threat is not None:
            raise ValueError("agreeing with the Threat range names no other Threat")

    def _check_understanding(self) -> None:
        if self.on_understanding is Judgement.DISAGREE and self.analyst_understanding in (
                None, self.subject.understanding):
            raise ValueError("disagreeing with Understanding names the Understanding the analyst judges, "
                             "which differs from the one shown")
        if self.on_understanding is Judgement.AGREE and self.analyst_understanding is not None:
            raise ValueError("agreeing with Understanding names no other level")

    @property
    def held(self) -> bool:
        """Whether the earned Threat range held the analyst's judgement: agreed, or a judged Threat inside it."""
        if self.analyst_threat is None:
            return True
        return self.subject.floor <= self.analyst_threat <= self.subject.ceiling

    @property
    def summary(self) -> str:
        """The entry in words: the range, then Understanding, each in a sentence of its own, then the reason."""
        subject = self.subject
        on_range = "agreed"
        if self.analyst_threat is not None:
            where = "inside" if self.held else "outside"
            on_range = f"disagreed, the analyst judges Threat {self.analyst_threat.name}, {where} the range"
        on_understanding = "agreed"
        if self.analyst_understanding is not None:
            on_understanding = f"disagreed, the analyst judges Understanding {self.analyst_understanding.name}"
        return (f"{subject.name} ({subject.satno}), {subject.range_text}: {on_range}. "
                f"Understanding {subject.understanding.name}: {on_understanding}. Reason: {self.reason}.")


def _same_picture(a: Adjudication, b: Adjudication) -> bool:
    return (a.subject.satno, a.subject.ledger_hash, a.analyst) == (b.subject.satno, b.subject.ledger_hash, b.analyst)


def record(log: tuple[Adjudication, ...], entry: Adjudication) -> tuple[Adjudication, ...]:
    """The log with *entry* added last; the old log is left as it was.

    A second adjudication of the same picture by the same analyst replaces
    the first, so changing one's mind does not count twice. Past MAX_HELD the
    oldest are dropped.
    """
    kept = tuple(e for e in log if not _same_picture(e, entry))
    return (*kept, entry)[-MAX_HELD:]


@dataclass(frozen=True)
class CoverageReport:
    """How often the earned Threat range held the analyst's judgement, once there are enough adjudications.

    *rate* is None until MIN_FOR_COVERAGE adjudications exist. *sentence* is
    what the operator reads: a count, never a percentage.
    """

    count: int
    held: int
    rate: float | None
    sentence: str


def _needed(count: int) -> str:
    more = MIN_FOR_COVERAGE - count
    verb = "is" if more == 1 else "are"
    return f"A coverage rate needs {MIN_FOR_COVERAGE}, so {more} more {verb} needed."


def coverage_report(log: tuple[Adjudication, ...]) -> CoverageReport:
    """The coverage report over *log*: the rate once MIN_FOR_COVERAGE exist, else how many more are needed."""
    count = len(log)
    held = sum(1 for e in log if e.held)
    if count >= MIN_FOR_COVERAGE:
        return CoverageReport(count=count, held=held, rate=held / count, sentence=(
            f"The earned Threat range held the analyst's judgement in {held} of {count} adjudications."))
    if count == 0:
        recorded = "No adjudications are recorded yet."
    elif count == 1:
        recorded = "1 adjudication is recorded."
    else:
        recorded = f"{count} adjudications are recorded."
    return CoverageReport(count=count, held=held, rate=None, sentence=f"{recorded} {_needed(count)}")
