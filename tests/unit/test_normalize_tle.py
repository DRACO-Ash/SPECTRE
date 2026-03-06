"""Unit tests for _normalize_tle_line1 in sipc.stk_adapter.com_session."""

from __future__ import annotations

import pytest

from sipc.stk_adapter.com_session import _normalize_tle_line1


# Reference TLE line 1 for SATNO 39034 (the failing case).
# Exponent sign for second derivative at 0-indexed position 50 is '+'.
_TLE_39034 = "1 39034U 12075A   26025.79842163  .00000000  00000+0  10000-2 0  9999 0"


class TestNormalizeTleLine1:
    def test_passthrough_non_line1(self) -> None:
        line = "2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.72125391563537"
        assert _normalize_tle_line1(line) == line

    def test_passthrough_short_line(self) -> None:
        line = "1 12345"
        assert _normalize_tle_line1(line) == line

    def test_mantissa_sign_first_deriv_replaced(self) -> None:
        # '+' at 0-indexed 33 (col 34) should become space
        line = "1 25544U 98067A   26025.50000000 +.00001000  00000+0  10000-3 0  9999 0"
        result = _normalize_tle_line1(line)
        assert result[33] == " "

    def test_mantissa_sign_second_deriv_replaced(self) -> None:
        # '+' at 0-indexed 44 (col 45) should become space
        line = "1 25544U 98067A   26025.50000000  .00001000 +00000+0  10000-3 0  9999 0"
        result = _normalize_tle_line1(line)
        assert result[44] == " "

    def test_exponent_sign_second_deriv_replaced(self) -> None:
        # '+' at 0-indexed 50 (col 51) — the failing case for SATNO 39034
        result = _normalize_tle_line1(_TLE_39034)
        assert result[50] == " ", f"Expected space at idx 50, got {result[50]!r}"

    def test_mantissa_sign_bstar_replaced(self) -> None:
        # '+' at 0-indexed 53 (col 54) should become space
        line = "1 25544U 98067A   26025.50000000  .00001000  00000+0 +10000-3 0  9999 0"
        result = _normalize_tle_line1(line)
        assert result[53] == " "

    def test_exponent_sign_bstar_replaced(self) -> None:
        # '+' at 0-indexed 59 (col 60) should become space
        line = "1 25544U 98067A   26025.50000000  .00001000  00000+0  10000+3 0  9999 0"
        result = _normalize_tle_line1(line)
        assert result[59] == " "

    def test_negative_signs_preserved(self) -> None:
        # '-' signs must never be touched
        line = "1 25544U 98067A   26025.50000000 -.00001000  00000-0  10000-3 0  9999 0"
        result = _normalize_tle_line1(line)
        assert result[33] == "-"
        assert result[50] == "-"
        assert result[59] == "-"

    def test_39034_all_plus_normalised(self) -> None:
        result = _normalize_tle_line1(_TLE_39034)
        # No '+' should remain in any of the five sign positions
        for idx in (33, 44, 50, 53, 59):
            assert result[idx] != "+", f"'+' still present at index {idx}"

    def test_other_plus_characters_untouched(self) -> None:
        # '+' in the line number, satellite number, or elsewhere must not be touched
        line = _TLE_39034
        result = _normalize_tle_line1(line)
        # Line starts with '1 ' — position 0 must be '1'
        assert result[0] == "1"
