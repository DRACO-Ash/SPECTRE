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

    def test_exponent_sign_second_deriv_preserved(self) -> None:
        # '+' at 0-indexed 50 (col 51) is the exponent sign — must NOT become space.
        # STK rejects a space at this position ("Failed to add the TLE").
        result = _normalize_tle_line1(_TLE_39034)
        assert result[50] == "+", f"Expected '+' at idx 50, got {result[50]!r}"

    def test_mantissa_sign_bstar_replaced(self) -> None:
        # '+' at 0-indexed 53 (col 54) should become space
        line = "1 25544U 98067A   26025.50000000  .00001000  00000+0 +10000-3 0  9999 0"
        result = _normalize_tle_line1(line)
        assert result[53] == " "

    def test_exponent_sign_bstar_preserved(self) -> None:
        # '+' at 0-indexed 59 (col 60) is the BSTAR exponent sign — must NOT become space.
        line = "1 25544U 98067A   26025.50000000  .00001000  00000+0  10000+3 0  9999 0"
        result = _normalize_tle_line1(line)
        assert result[59] == "+", f"Expected '+' at idx 59, got {result[59]!r}"

    def test_space_at_exponent_sign_normalised_to_plus(self) -> None:
        # UDL sometimes produces non-standard 72-char TLEs with extra spaces that
        # shift field positions. Reproduce the live failure for SATNO 33274:
        # both second-deriv and BSTAR had '00000 0' (space as exponent sign).
        # The regex fix must work regardless of TLE length.
        line = "1 33274U 08038A   26065.97128064  -.00000308  00000 0  00000 0 0  9999 3"
        assert len(line) == 72  # confirm non-standard
        result = _normalize_tle_line1(line)
        assert "00000+0" in result, f"Expected '00000+0' in result, got: {result!r}"
        assert "00000 0" not in result, f"'00000 0' still present — exponent space not fixed"

    def test_negative_signs_preserved(self) -> None:
        # '-' signs must never be touched at any sign position
        line = "1 25544U 98067A   26025.50000000 -.00001000  00000-0  10000-3 0  9999 0"
        result = _normalize_tle_line1(line)
        assert result[33] == "-"
        assert result[50] == "-"
        assert result[59] == "-"

    def test_39034_mantissa_plus_normalised_exponent_preserved(self) -> None:
        result = _normalize_tle_line1(_TLE_39034)
        # Mantissa sign positions: '+' replaced with space
        for idx in (33, 44, 53):
            assert result[idx] != "+", f"'+' still present at mantissa index {idx}"
        # Exponent sign position 50: '+' must be preserved (not replaced with space)
        assert result[50] == "+", "Exponent sign at idx 50 must remain '+'"

    def test_other_plus_characters_untouched(self) -> None:
        # '+' in the line number, satellite number, or elsewhere must not be touched
        line = _TLE_39034
        result = _normalize_tle_line1(line)
        # Line starts with '1 ' — position 0 must be '1'
        assert result[0] == "1"
