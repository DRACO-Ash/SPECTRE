"""What produced a result: the code, the calibration and the inputs.

No domain output carried any of this, so a verdict or recommendation could
not be traced to the element sets and code behind it once the session ended
(audit F-121). Each top-level result (ScenarioResult, ThreatAssessment,
PolAssessment) now carries a :class:`Provenance`.

An input is identified by a SHA-256 of a canonical form: a TLE by its lines,
trimmed, joined with newlines; any other value by its JSON, keys sorted.
The same inputs give the same hashes, so a result can be matched to the
data it was computed from.

A figure inside a result also says what it rests on, as a :class:`FigureBasis`:
a lookup (a constant or rule of thumb, uncalibrated), a sample distribution
over Monte Carlo runs of a hypothesis, or a figure computed from element sets.
A figure derived from others is never stronger than the weakest of them
(:func:`weakest`), so a computed figure can sit beside a lookup without
lending it its standing (SPC-101).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import spectre
from spectre.domain.manoeuvre_calibration import CALIBRATION_SOURCE


@dataclass(frozen=True)
class InputRef:
    """One input to a result: what it was, when (for a TLE), and its hash."""

    label: str
    sha256: str
    epoch: datetime | None = None


@dataclass(frozen=True)
class Provenance:
    """The code version, calibration source and inputs behind a result."""

    code_version: str
    calibration_source: str
    inputs: tuple[InputRef, ...]
    computed_at: datetime


class Basis(StrEnum):
    """What a figure rests on, declared weakest first."""

    LOOKUP = "lookup"          # a constant or rule of thumb, uncalibrated
    SAMPLED = "sampled"        # a distribution over Monte Carlo samples of a hypothesis
    COMPUTED = "computed"      # propagated or solved from element sets


_STRENGTH: dict[Basis, int] = {Basis.LOOKUP: 0, Basis.SAMPLED: 1, Basis.COMPUTED: 2}


@dataclass(frozen=True)
class FigureBasis:
    """One figure's basis and, in the operator's words, the rule behind it.

    Any m/s to km/s scaling in *note* names its km/s side, the unit the figure carries.
    """

    kind: Basis
    note: str


def weakest(*kinds: Basis) -> Basis:
    """The weakest of *kinds*: what a figure derived from them can claim."""
    if not kinds:
        raise ValueError("weakest() needs at least one basis")
    return min(kinds, key=_STRENGTH.__getitem__)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def tle_input(label: str, tle_text: str, epoch: datetime | None = None) -> InputRef:
    """A TLE as an input, hashed on its trimmed lines."""
    canonical = "\n".join(line.strip() for line in tle_text.strip().splitlines())
    return InputRef(label=label, sha256=_digest(canonical), epoch=epoch)


def _plain(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    return value


def _json_default(value: Any) -> Any:
    """An array by its values at full precision, so two states that print alike hash apart (SPC-111); else its text."""
    tolist = getattr(value, "tolist", None)
    return tolist() if callable(tolist) else str(value)


def value_input(label: str, value: Any) -> InputRef:
    """Any other input, hashed on its JSON with keys sorted."""
    return InputRef(label=label, sha256=_digest(json.dumps(_plain(value), sort_keys=True, default=_json_default)))


def provenance(inputs: Iterable[InputRef]) -> Provenance:
    """Provenance for a result computed now from *inputs*."""
    return Provenance(
        code_version=spectre.__version__,
        calibration_source=CALIBRATION_SOURCE,
        inputs=tuple(inputs),
        computed_at=datetime.now(UTC),
    )
