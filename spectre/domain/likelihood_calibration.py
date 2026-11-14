"""Decision Engine: the calibration harness for the update's likelihood (SPC-210, evaluation F-22).

The update after turn 1 (spectre.domain.turn_update) rests on a likelihood that is a deterministic custody rule: what
a turn lets us see of red is the bound red track's custody, and each red move gives what it gives for certain. Nothing
has tested that rule against what happened, so the update's probability has no demonstrated reliability. This module
is the harness a back-test runs through: it takes held histories, each a predicted probability and whether that
outcome came about, and reports their Brier score, a reliability table by bin of predicted probability and the sample
count. It names the data file by the SHA-256 of its bytes, and the code by SPECTRE's version string, the SHA-256 of
this module's bytes and, when a command ran it, the SHA-256 of that command's bytes; each hash covers that one file
and nothing else. scripts/calibrate_likelihood.py runs it on a file.

The score measures the predicted probabilities in the file, not the update: the harness never runs turn_update. It is
evidence about the update's custody likelihood only if those probabilities were produced by it for real held
outcomes, which the harness cannot check.

The histories it reads are plain text, UTF-8, comma-separated, one held history a line under the header
``history,predicted,observed``:

● history: an identifier, unique in the file, naming the held history, such as the record or event it came from;
● predicted: the probability, from 0 to 1, the update gave the outcome for that history, such as its share of the
  weight that red burnt in turn 1 after what custody showed;
● observed: 1 if the outcome came about, 0 if it did not, from a source other than the custody the update read.

No held history that fits exists in the repository (checked for SPC-210: the NOTSO cache holds reported events only,
with no probability the update gave and no window where red was seen not to burn; the manoeuvre evidence summarises
burns per object; no element-set or custody history is shipped). None is shipped, simulated or reported here, so the
likelihood stays uncalibrated, as every place the update's probability is shown says, until the owner supplies
histories. The tests run the harness on hand-made fixtures whose score is worked by hand; they are not calibration
evidence. Nothing here imports the web layer.
"""

from __future__ import annotations

import csv
import hashlib
import io
import math
from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import spectre

#: The header the histories carry, in order.
HEADER: tuple[str, ...] = ("history", "predicted", "observed")
#: How many equal bins of predicted probability the reliability table has unless asked for another number.
DEFAULT_BINS = 10
#: Where the code is, as the report names it.
CODE = "spectre/domain/likelihood_calibration.py"

_REFUSED = "Held histories refused: {why}."
_NO_HEADER = "no header: the first line must be history,predicted,observed"
_NONE = "no held histories, so no Brier score"
_FIELDS = "line {line}: 3 fields are needed, history,predicted,observed; it has {n}"
_NO_ID = "line {line}: the history needs an identifier"
_TWICE = "line {line}: history {history!r} is held twice"
_NOT_A_NUMBER = "line {line}: predicted {text!r} is not a number"
_NOT_A_PROBABILITY = "line {line}: predicted {text!r} is not a probability from 0 to 1"
_NOT_AN_OUTCOME = "line {line}: observed {text!r} must be 1, it came about, or 0, it did not"
_BINS = "the bins must be a whole number of at least 1; got {bins!r}"
_OUTCOMES: dict[str, int] = {"0": 0, "1": 1}

_HEAD = "Back-test of held histories (SPC-210): {n} from {data}, the file's SHA-256 {sha}."
_CODE_LINE = (
    "Code: SPECTRE {version}, by its version string; the scoring module {code}, SHA-256 {sha}{command}. Each SHA-256 "
    "covers that one file's bytes and nothing else."
)
_COMMAND = "; the command {path}, SHA-256 {sha}"
_BRIER = (
    "Brier score {brier:.4f} over {n} held histories: the mean squared difference between each predicted probability "
    "in the file and its outcome, 0 at best and 1 at worst."
)
_TABLE = "Reliability by predicted probability, each bin its count, mean predicted probability and observed rate:"
_BIN = "{low:.2f} to {high:.2f}: {count} {noun}, mean predicted {mean:.3f}, observed {rate:.3f}."
_EMPTY_BIN = "{low:.2f} to {high:.2f}: no histories."
_CAVEAT = (
    "The score measures the predicted probabilities in the file, not the update. It is evidence about the update's "
    "custody likelihood (spectre/domain/turn_update.py) only if those probabilities were produced by it for real held "
    "outcomes, which the harness cannot check."
)


class HistoriesRefusedError(ValueError):
    """Held histories the harness will not score, saying where and why."""

    def __init__(self, why: str) -> None:
        super().__init__(_REFUSED.format(why=why))


@dataclass(frozen=True)
class HeldHistory:
    """One held history: its identifier, the probability the update gave the outcome, and whether it came about."""

    history:   str
    predicted: float
    observed:  int


@dataclass(frozen=True)
class ReliabilityBin:
    """One bin of predicted probability, from *low* to *high*: how many histories fall in it, their mean predicted
    probability and the share whose outcome came about; both None for an empty bin."""

    low:            float
    high:           float
    count:          int
    mean_predicted: float | None
    observed_rate:  float | None

    @property
    def line(self) -> str:
        if self.mean_predicted is None or self.observed_rate is None:
            return _EMPTY_BIN.format(low=self.low, high=self.high)
        noun = "history" if self.count == 1 else "histories"
        return _BIN.format(low=self.low, high=self.high, count=self.count, noun=noun, mean=self.mean_predicted,
                           rate=self.observed_rate)


@dataclass(frozen=True)
class CalibrationReport:
    """A back-test's result: the sample count, the Brier score and the reliability table, with what the data is, its
    SHA-256, the code's version and this module's SHA-256, and the command that ran it with its SHA-256, if any."""

    samples:      int
    brier:        float
    bins:         tuple[ReliabilityBin, ...]
    data:         str
    data_sha256:  str
    code_version: str
    code_sha256:  str
    #: The command that ran the harness and the SHA-256 of its bytes; None when it was called directly.
    command:      tuple[str, str] | None = None

    @property
    def lines(self) -> tuple[str, ...]:
        """The report in words, the data and code first, then the score, the table and what it is evidence of."""
        return (
            _HEAD.format(n=self.samples, data=self.data, sha=self.data_sha256),
            _CODE_LINE.format(
                version=self.code_version, code=CODE, sha=self.code_sha256,
                command="" if self.command is None else _COMMAND.format(path=self.command[0], sha=self.command[1]),
            ),
            _BRIER.format(brier=self.brier, n=self.samples),
            _TABLE,
            *(b.line for b in self.bins),
            _CAVEAT,
        )


def _probability(text: str, line: int) -> float:
    try:
        value = float(text)
    except ValueError:
        raise HistoriesRefusedError(_NOT_A_NUMBER.format(line=line, text=text)) from None
    if not (math.isfinite(value) and 0.0 <= value <= 1.0):
        raise HistoriesRefusedError(_NOT_A_PROBABILITY.format(line=line, text=text))
    return value


def _row(fields: Sequence[str], line: int, seen: set[str]) -> HeldHistory:
    if len(fields) != len(HEADER):
        raise HistoriesRefusedError(_FIELDS.format(line=line, n=len(fields)))
    history, predicted, observed = (f.strip() for f in fields)
    if not history:
        raise HistoriesRefusedError(_NO_ID.format(line=line))
    if history in seen:
        raise HistoriesRefusedError(_TWICE.format(line=line, history=history))
    if observed not in _OUTCOMES:
        raise HistoriesRefusedError(_NOT_AN_OUTCOME.format(line=line, text=observed))
    seen.add(history)
    return HeldHistory(history, _probability(predicted, line), _OUTCOMES[observed])


def _records(text: str) -> list[tuple[int, list[str]]]:
    """Each non-blank record of *text* with the physical line it starts on: a quoted field may span lines, so the
    record's number and its line can differ."""
    reader = csv.reader(io.StringIO(text))
    found, ended = [], 0
    for fields in reader:
        if fields:
            found.append((ended + 1, fields))
        ended = reader.line_num
    return found


def read_histories(text: str) -> tuple[HeldHistory, ...]:
    """The held histories in *text*, in order, under the header; HistoriesRefusedError naming the physical line a
    record starts on for anything else: no header, no history, a row without three fields, an identifier missing or
    held twice, a predicted probability that is not a number from 0 to 1, or an outcome other than 1 or 0. Blank
    lines are passed over. The header is matched exactly, case included."""
    rows = _records(text)
    if not rows or tuple(f.strip() for f in rows[0][1]) != HEADER:
        raise HistoriesRefusedError(_NO_HEADER)
    seen: set[str] = set()
    histories = tuple(_row(fields, n, seen) for n, fields in rows[1:])
    if not histories:
        raise HistoriesRefusedError(_NONE)
    return histories


def brier_score(histories: Sequence[HeldHistory]) -> float:
    """The mean of each predicted probability's squared difference from its outcome: 0 at best, 1 at worst."""
    if not histories:
        raise HistoriesRefusedError(_NONE)
    return math.fsum((h.predicted - h.observed) ** 2 for h in histories) / len(histories)


def _bin_of(predicted: float, bins: int) -> int:
    """The bin a probability falls in: each bin opens at its lower edge. The probability is read as the shortest
    decimal that gives back the parsed float (its repr), not as the text the file wrote, so "0.3" and "0.30" alike
    read as 0.3 and open the fourth of 10 bins rather than fall below it by binary rounding; 1 falls in the last."""
    return min(math.floor(Fraction(repr(predicted)) * bins), bins - 1)


def reliability(histories: Sequence[HeldHistory], bins: int = DEFAULT_BINS) -> tuple[ReliabilityBin, ...]:
    """The reliability table: *bins* equal bins of predicted probability from 0 to 1, each with its count, its
    histories' mean predicted probability and the share whose outcome came about."""
    if isinstance(bins, bool) or not isinstance(bins, int) or bins < 1:
        raise HistoriesRefusedError(_BINS.format(bins=bins))
    members: list[list[HeldHistory]] = [[] for _ in range(bins)]
    for history in histories:
        members[_bin_of(history.predicted, bins)].append(history)
    table = []
    for k, held in enumerate(members):
        mean = math.fsum(h.predicted for h in held) / len(held) if held else None
        rate = sum(h.observed for h in held) / len(held) if held else None
        table.append(ReliabilityBin(k / bins, (k + 1) / bins, len(held), mean, rate))
    return tuple(table)


def _code_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def calibration_report(
    histories: Sequence[HeldHistory], *, data: str, data_sha256: str, bins: int = DEFAULT_BINS,
    command: tuple[str, str] | None = None,
) -> CalibrationReport:
    """The report on *histories*, which *data* names and *data_sha256* identifies: the sample count, the Brier score
    and the reliability table in *bins* bins, with the code's version and this module's SHA-256, and *command*, the
    path and SHA-256 of the command that ran it, when one did."""
    return CalibrationReport(
        samples=len(histories), brier=brier_score(histories), bins=reliability(histories, bins), data=data,
        data_sha256=data_sha256, code_version=spectre.__version__, code_sha256=_code_sha256(), command=command,
    )
