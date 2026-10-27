"""combined_altitude_plane_change makes the whole plane change on the higher burn.

Audit F-075: the docstring said the change was split across both burns and
then that it was all done at one; the code does the latter. The docstring now
says so, and this pins the behaviour it describes: the lower burn is the plain
Hohmann impulse whichever way the transfer goes.
"""

from __future__ import annotations

import pytest

from spectre.astro.tactical import combined_altitude_plane_change
from spectre.astro.transfers import hohmann


def test_raising_the_first_burn_is_plain_hohmann() -> None:
    combined = combined_altitude_plane_change(7000.0, 9000.0, 10.0)
    assert combined.delta_v_1 == pytest.approx(hohmann(7000.0, 9000.0).delta_v_1, rel=1e-12)


def test_lowering_the_second_burn_is_plain_hohmann() -> None:
    combined = combined_altitude_plane_change(9000.0, 7000.0, 10.0)
    assert combined.delta_v_2 == pytest.approx(hohmann(9000.0, 7000.0).delta_v_2, rel=1e-12)


def test_the_docstring_no_longer_claims_a_split() -> None:
    assert "split across both burns" not in (combined_altitude_plane_change.__doc__ or "")
