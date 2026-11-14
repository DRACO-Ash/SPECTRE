"""The calibration harness for the update's likelihood (SPC-210, evaluation F-22).

The harness takes held histories, each a probability the update gave an outcome and whether it came about, and
reports their Brier score, a reliability table by bin and the sample count, with the data identified by its SHA-256
and the code by its version and its own SHA-256. No held history that fits exists in the repository, so these tests
run it on small hand-made fixtures whose score is worked by hand below. They test the arithmetic; they are not
calibration evidence, and nothing here reports a Brier score as such.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import spectre
from spectre.domain import likelihood_calibration as lc
from spectre.domain.likelihood_calibration import (
    DEFAULT_BINS,
    HEADER,
    CalibrationReport,
    HeldHistory,
    HistoriesRefusedError,
    brier_score,
    calibration_report,
    read_histories,
    reliability,
)

#: Four hand-made histories. Squared errors: (0.9 - 1)^2 = 0.01, (0.9 - 0)^2 = 0.81, (0.2 - 0)^2 = 0.04 and
#: (0.5 - 1)^2 = 0.25, which sum to 1.11, so the Brier score is 1.11 / 4 = 0.2775.
_FOUR = "history,predicted,observed\nh1,0.9,1\nh2,0.9,0\nh3,0.2,0\nh4,0.5,1\n"
_SHA = hashlib.sha256(_FOUR.encode()).hexdigest()
_HEAD = "history,predicted,observed\n"


def _four() -> tuple[HeldHistory, ...]:
    return read_histories(_FOUR)


class TestTheFormat:
    def test_the_header_names_the_three_columns(self) -> None:
        assert HEADER == ("history", "predicted", "observed")
        assert DEFAULT_BINS == 10

    def test_rows_are_read_in_order(self) -> None:
        assert _four() == (
            HeldHistory("h1", 0.9, 1), HeldHistory("h2", 0.9, 0), HeldHistory("h3", 0.2, 0), HeldHistory("h4", 0.5, 1),
        )

    def test_a_blank_last_line_and_a_crlf_ending_are_read(self) -> None:
        assert read_histories("history,predicted,observed\r\nx,0,0\r\n\r\n") == (HeldHistory("x", 0.0, 0),)

    @pytest.mark.parametrize(("text", "why"), [
        ("", "no header: the first line must be history,predicted,observed"),
        ("id,p,o\nx,0.5,1\n", "no header: the first line must be history,predicted,observed"),
        ("history,predicted,observed\n", "no held histories, so no Brier score"),
        ("history,predicted,observed\nx,0.5\n", "line 2: 3 fields are needed, history,predicted,observed; it has 2"),
        ("history,predicted,observed\n,0.5,1\n", "line 2: the history needs an identifier"),
        ("history,predicted,observed\nx,0.5,1\nx,0.2,0\n", "line 3: history 'x' is held twice"),
        ("history,predicted,observed\nx,high,1\n", "line 2: predicted 'high' is not a number"),
        ("history,predicted,observed\nx,nan,1\n", "line 2: predicted 'nan' is not a probability from 0 to 1"),
        ("history,predicted,observed\nx,1.2,1\n", "line 2: predicted '1.2' is not a probability from 0 to 1"),
        ("history,predicted,observed\nx,-0.1,1\n", "line 2: predicted '-0.1' is not a probability from 0 to 1"),
        (f"{_HEAD}x,0.5,yes\n", "line 2: observed 'yes' must be 1, it came about, or 0, it did not"),
        (f"{_HEAD}x,0.5,0.5\n", "line 2: observed '0.5' must be 1, it came about, or 0, it did not"),
        (f'{_HEAD}"two\nlines",0.5,1\nx,bad,1\n', "line 4: predicted 'bad' is not a number"),
        (f'{_HEAD}x,0.5,1\n"y\nz",bad,1\n', "line 3: predicted 'bad' is not a number"),
    ])
    def test_anything_else_is_refused_naming_where(self, text: str, why: str) -> None:
        with pytest.raises(HistoriesRefusedError) as refused:
            read_histories(text)
        assert str(refused.value) == f"Held histories refused: {why}."


class TestTheScore:
    def test_the_brier_score_is_the_mean_squared_error_worked_by_hand(self) -> None:
        assert brier_score(_four()) == pytest.approx(0.2775, abs=1e-15)

    def test_a_perfect_forecast_scores_0_and_the_worst_scores_1(self) -> None:
        assert brier_score((HeldHistory("a", 1.0, 1), HeldHistory("b", 0.0, 0))) == 0.0
        assert brier_score((HeldHistory("a", 0.0, 1), HeldHistory("b", 1.0, 0))) == 1.0

    def test_no_histories_have_no_score(self) -> None:
        with pytest.raises(HistoriesRefusedError, match="no held histories, so no Brier score"):
            brier_score(())


class TestTheReliabilityTable:
    def test_each_bin_holds_its_count_mean_prediction_and_observed_rate(self) -> None:
        bins = reliability(_four(), 2)
        assert [(b.low, b.high, b.count) for b in bins] == [(0.0, 0.5, 1), (0.5, 1.0, 3)]
        assert bins[0].mean_predicted == pytest.approx(0.2) and bins[0].observed_rate == 0.0
        assert bins[1].mean_predicted == pytest.approx((0.9 + 0.9 + 0.5) / 3)
        assert bins[1].observed_rate == pytest.approx(2 / 3)

    def test_an_empty_bin_says_none(self) -> None:
        bins = reliability(_four(), DEFAULT_BINS)
        assert len(bins) == 10
        assert [b.count for b in bins] == [0, 0, 1, 0, 0, 1, 0, 0, 0, 2]
        assert (bins[0].mean_predicted, bins[0].observed_rate) == (None, None)

    @pytest.mark.parametrize(("p", "n", "k"), [(0.3, 10, 3), (0.7, 10, 7), (0.57, 100, 57), (1.0, 10, 9), (0.0, 10, 0)])
    def test_a_probability_on_an_edge_falls_in_the_bin_it_opens(self, p: float, n: int, k: int) -> None:
        bins = reliability((HeldHistory("e", p, 1),), n)
        assert [b.count for b in bins].index(1) == k

    @pytest.mark.parametrize("written", ["0.3", "0.30", "0.300000"])
    def test_a_probability_is_binned_by_the_parsed_floats_shortest_decimal_not_its_text(self, written: str) -> None:
        (history,) = read_histories(f"{_HEAD}e,{written},1\n")
        assert [b.count for b in reliability((history,), 10)].index(1) == 3

    @pytest.mark.parametrize("n", [0, -1, 1.5, True])
    def test_a_bin_count_below_1_or_not_whole_is_refused(self, n: object) -> None:
        with pytest.raises(HistoriesRefusedError, match="the bins must be a whole number of at least 1"):
            reliability(_four(), n)  # type: ignore[arg-type]


class TestTheReport:
    def test_it_identifies_the_data_and_the_code(self) -> None:
        report = calibration_report(_four(), data="hand-made fixture", data_sha256=_SHA, bins=2)
        code = hashlib.sha256(Path(lc.__file__).read_bytes()).hexdigest()
        assert isinstance(report, CalibrationReport)
        assert (report.samples, report.data, report.data_sha256) == (4, "hand-made fixture", _SHA)
        assert (report.code_version, report.code_sha256) == (spectre.__version__, code)
        assert report.brier == brier_score(_four())

    def test_its_lines_say_the_score_the_table_and_the_sample_count(self) -> None:
        report = calibration_report(_four(), data="hand-made fixture", data_sha256=_SHA, bins=2)
        assert report.lines == (
            f"Back-test of held histories (SPC-210): 4 from hand-made fixture, the file's SHA-256 {_SHA}.",
            f"Code: SPECTRE {spectre.__version__}, by its version string; the scoring module "
            f"spectre/domain/likelihood_calibration.py, SHA-256 {report.code_sha256}. Each SHA-256 covers that one "
            "file's bytes and nothing else.",
            "Brier score 0.2775 over 4 held histories: the mean squared difference between each predicted probability "
            "in the file and its outcome, 0 at best and 1 at worst.",
            "Reliability by predicted probability, each bin its count, mean predicted probability and observed rate:",
            "0.00 to 0.50: 1 history, mean predicted 0.200, observed 0.000.",
            "0.50 to 1.00: 3 histories, mean predicted 0.767, observed 0.667.",
            "The score measures the predicted probabilities in the file, not the update. It is evidence about the "
            "update's custody likelihood (spectre/domain/turn_update.py) only if those probabilities were produced "
            "by it for real held outcomes, which the harness cannot check.",
        )

    def test_a_command_that_ran_it_is_named_with_its_own_hash(self) -> None:
        report = calibration_report(
            _four(), data="hand-made fixture", data_sha256=_SHA, bins=2, command=("scripts/x.py", "ab" * 32),
        )
        assert report.lines[1] == (
            f"Code: SPECTRE {spectre.__version__}, by its version string; the scoring module "
            f"spectre/domain/likelihood_calibration.py, SHA-256 {report.code_sha256}; the command scripts/x.py, "
            f"SHA-256 {'ab' * 32}. Each SHA-256 covers that one file's bytes and nothing else."
        )

    def test_an_empty_bin_is_said(self) -> None:
        report = calibration_report(_four(), data="hand-made fixture", data_sha256=_SHA)
        assert "0.00 to 0.10: no histories." in report.lines
        assert "0.90 to 1.00: 2 histories, mean predicted 0.900, observed 0.500." in report.lines

    def test_no_histories_give_no_report(self) -> None:
        with pytest.raises(HistoriesRefusedError, match="no held histories"):
            calibration_report((), data="none", data_sha256=_SHA)
