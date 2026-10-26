"""What produced a result: the code, the calibration and the inputs.

No domain output carried any of this, so a verdict or recommendation could
not be traced to the element sets and code behind it once the session ended
(audit F-121). Each top-level result (ScenarioResult, ThreatAssessment,
PolAssessment) now carries a :class:`Provenance`.

An input is identified by a SHA-256 of a canonical form: a TLE by its lines,
trimmed, joined with newlines; any other value by its JSON, keys sorted.
The same inputs give the same hashes, so a result can be matched to the
data it was computed from.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
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


def value_input(label: str, value: Any) -> InputRef:
    """Any other input, hashed on its JSON with keys sorted."""
    return InputRef(label=label, sha256=_digest(json.dumps(_plain(value), sort_keys=True, default=str)))


def provenance(inputs: Iterable[InputRef]) -> Provenance:
    """Provenance for a result computed now from *inputs*."""
    return Provenance(
        code_version=spectre.__version__,
        calibration_source=CALIBRATION_SOURCE,
        inputs=tuple(inputs),
        computed_at=datetime.now(UTC),
    )
