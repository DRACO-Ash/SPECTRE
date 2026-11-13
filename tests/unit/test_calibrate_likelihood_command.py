"""scripts/calibrate_likelihood.py: the back-test of the update's likelihood on a file (SPC-210, evaluation F-22).

The command reads one file of held histories and prints the harness's report: the file named with its SHA-256, the
code, the Brier score, the reliability table and the sample count. Exit codes: 0 when the report is printed, 2 for a
usage error, 3 when there is nothing to score. The file here is a hand-made fixture whose score is worked by hand in
tests/unit/test_likelihood_calibration.py; it is not calibration evidence. The script is repository-only.
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from tests.unit.test_deployment_contract import _repo_only
from tests.unit.test_likelihood_calibration import _FOUR


@pytest.fixture(scope="module")
def command() -> ModuleType:
    script = _repo_only("scripts/calibrate_likelihood.py")
    spec = importlib.util.spec_from_file_location("_calibrate_likelihood", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_calibrate_likelihood"] = module
    spec.loader.exec_module(module)
    return module


def _file(tmp_path: Path, content: bytes) -> Path:
    path = tmp_path / "held.csv"
    path.write_bytes(content)
    return path


def test_it_prints_the_report_naming_the_file_and_its_hash(
    command: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    path = _file(tmp_path, _FOUR.encode())
    assert command.main([str(path), "--bins", "2"]) == command.REPORTED == 0
    out = capsys.readouterr().out.splitlines()
    sha = hashlib.sha256(_FOUR.encode()).hexdigest()
    script = hashlib.sha256(_repo_only("scripts/calibrate_likelihood.py").read_bytes()).hexdigest()
    assert out[0] == f"Back-test of held histories (SPC-210): 4 from {path}, the file's SHA-256 {sha}."
    assert f"; the command scripts/calibrate_likelihood.py, SHA-256 {script}. " in out[1]
    assert out[2].startswith("Brier score 0.2775 over 4 held histories")
    assert out[4:6] == [
        "0.00 to 0.50: 1 history, mean predicted 0.200, observed 0.000.",
        "0.50 to 1.00: 3 histories, mean predicted 0.767, observed 0.667.",
    ]
    assert len(out) == 7


def test_it_bins_in_tens_unless_asked(command: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert command.main([str(_file(tmp_path, _FOUR.encode()))]) == 0
    assert len(capsys.readouterr().out.splitlines()) == 15


@pytest.mark.parametrize(("content", "said"), [
    (b"history,predicted,observed\n", "Held histories refused: no held histories, so no Brier score."),
    (b"\xff\xfe", "it is not UTF-8 text."),
])
def test_nothing_to_score_says_why(
    command: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str], content: bytes, said: str,
) -> None:
    assert command.main([str(_file(tmp_path, content))]) == command.NOTHING == 3
    assert said in capsys.readouterr().err


def test_a_missing_file_says_it_cannot_be_read(
    command: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    missing = tmp_path / "absent.csv"
    assert command.main([str(missing)]) == 3
    assert capsys.readouterr().err.startswith(f"Cannot read {missing}: ")


@pytest.mark.parametrize("bins", ["0", "-1", "1001", "2.5", "ten"])
def test_a_bin_count_outside_1_to_1000_is_a_usage_error(
    command: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str], bins: str,
) -> None:
    with pytest.raises(SystemExit) as stopped:
        command.main([str(_file(tmp_path, _FOUR.encode())), "--bins", bins])
    assert stopped.value.code == command.USAGE == 2
    assert "a whole number of bins from 1 to 1,000" in capsys.readouterr().err


def test_the_most_bins_allowed_are_reported(
    command: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    assert command.main([str(_file(tmp_path, _FOUR.encode())), "--bins", "1000"]) == 0
    assert command.MAX_BINS == 1000
    assert len(capsys.readouterr().out.splitlines()) == 1005


def test_a_file_with_a_byte_order_mark_is_read(
    command: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    content = b"\xef\xbb\xbf" + _FOUR.encode()
    path = _file(tmp_path, content)
    assert command.main([str(path), "--bins", "2"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].endswith(f"the file's SHA-256 {hashlib.sha256(content).hexdigest()}.")
    assert out[2].startswith("Brier score 0.2775 over 4 held histories")


def test_a_header_in_another_case_is_still_refused(
    command: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    path = _file(tmp_path, _FOUR.replace("history,predicted,observed", "History,Predicted,Observed").encode())
    assert command.main([str(path)]) == 3
    assert "no header" in capsys.readouterr().err


def test_a_usage_error_exits_2(command: ModuleType) -> None:
    with pytest.raises(SystemExit) as stopped:
        command.main([])
    assert stopped.value.code == command.USAGE == 2
