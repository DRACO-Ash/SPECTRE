"""The decimal field pattern of spectre.astro.elset_check reads exactly what it read before release 0.48.6.

SonarQube raised python:S8786 on " *[+-]?\\d*\\.?\\d+ *": "\\d*" and "\\d+" can split a run of digits many ways, so a
field that fails backtracks through each split. The pattern was rewritten as digits with an optional fraction, or a
bare fraction, which splits a run one way only. These tests hold that the new pattern accepts and refuses exactly the
strings the old one did: every string up to six characters over an alphabet holding each kind of character the
format or float() could meet, and the drag fields of real element sets.
"""

from __future__ import annotations

import itertools
import re

import pytest

from spectre.astro.elset_check import _DECIMAL, check_elset
from tests.unit._decision_reference import GEO_DRIFT_IN, PLANE_CHANGE

#: The pattern as it stood to 0.48.5, the oracle.
_BEFORE = re.compile(r" *[+-]?\d*\.?\d+ *", re.ASCII)

#: A space, both signs, two ASCII digits, the point, an exponent letter, an underscore, a tab and a non-ASCII digit
#: (ARABIC-INDIC DIGIT THREE, which float() reads and re.ASCII keeps out of \d).
_ALPHABET = " +-09.e_\t٣"


def _every_string(longest: int) -> list[str]:
    return ["".join(chars) for n in range(longest + 1) for chars in itertools.product(_ALPHABET, repeat=n)]


def test_every_short_string_reads_as_it_did() -> None:
    differs = [s for s in _every_string(6) if bool(_DECIMAL.fullmatch(s)) != bool(_BEFORE.fullmatch(s))]
    assert differs == []


@pytest.mark.parametrize("field", [
    " .00002182", "-.00002182", " 97.4000", "97.4", "  1", "1.", ".", "+", "", " ", "1.2.3", "1e5", "1_0", "--1",
    " -0.00000999", "+.5 ", "12345678901234567890.12345678901234567890",
])
def test_named_fields_read_as_they_did(field: str) -> None:
    assert bool(_DECIMAL.fullmatch(field)) == bool(_BEFORE.fullmatch(field))


@pytest.mark.parametrize("tle", [PLANE_CHANGE.red_tle, PLANE_CHANGE.blue_tle, GEO_DRIFT_IN.red_tle])
def test_reference_sets_still_pass(tle: str) -> None:
    first_derivative = tle.splitlines()[0][33:43]
    assert _DECIMAL.fullmatch(first_derivative) and _BEFORE.fullmatch(first_derivative)
    assert check_elset(tle).accepted


def test_a_long_failing_field_is_refused() -> None:
    """A long run of digits that fails at its end is refused, as before."""
    field = "1" * 5000 + "x"
    assert _DECIMAL.fullmatch(field) is None and _BEFORE.fullmatch(field) is None
