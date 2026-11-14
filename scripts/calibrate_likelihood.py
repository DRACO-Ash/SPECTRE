#!/usr/bin/env python3
"""Back-test the update's likelihood on held histories and report a Brier score (SPC-210, evaluation F-22).

Reads one file of held histories, plain text, UTF-8 with or without a byte order mark, under the header
``history,predicted,observed``, matched exactly: each line a held history's identifier, the probability from 0 to 1
the update gave the outcome, and 1 if it came about or 0 if it did not (spectre/domain/likelihood_calibration.py says
each field in full). Prints the report: the file named with the SHA-256 of its bytes, the code with SPECTRE's version
string and the SHA-256 of the scoring module's bytes and of this command's, each hash covering that one file only, the
Brier score, the reliability table by bin of predicted probability and the sample count. It writes nothing.

    python scripts/calibrate_likelihood.py HISTORIES.csv [--bins N]

N is a whole number of bins from 1 to 1,000, 10 unless given. The score measures the probabilities in the file, not
the update: it is evidence about the update's custody likelihood only if those probabilities were produced by it for
real held outcomes, which the harness cannot check. No such file is in the repository, so the likelihood stays
uncalibrated until the owner supplies one.

Exit codes: 0 the report was printed; 2 a usage error, a number of bins outside 1 to 1,000 included; 3 nothing to
score: a file that cannot be read, is not UTF-8, or holds histories the harness refuses.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from collections.abc import Sequence
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spectre.domain.likelihood_calibration import (  # noqa: E402 - after the repository root is on the path
    DEFAULT_BINS,
    HistoriesRefusedError,
    calibration_report,
    read_histories,
)

REPORTED, USAGE, NOTHING = 0, 2, 3
#: The most bins the reliability table may have: more says nothing a file of held histories could fill.
MAX_BINS = 1000
#: This command as the report names it.
COMMAND = "scripts/calibrate_likelihood.py"
_BINS = "a whole number of bins from 1 to 1,000 is needed; got {text!r}"


def _bins(text: str) -> int:
    """The number of bins *text* asks for; a usage error unless it is a whole number from 1 to MAX_BINS."""
    try:
        bins = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(_BINS.format(text=text)) from None
    if not 1 <= bins <= MAX_BINS:
        raise argparse.ArgumentTypeError(_BINS.format(text=text))
    return bins


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Back-test held histories of predicted probabilities and outcomes.")
    parser.add_argument("histories", type=Path, help="the held histories: history,predicted,observed")
    parser.add_argument(
        "--bins", type=_bins, default=DEFAULT_BINS,
        help=f"equal bins of predicted probability, a whole number from 1 to {MAX_BINS:,} (default {DEFAULT_BINS})",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Print the report on the file named in *argv*; the exit code."""
    args = _parser().parse_args(argv)
    try:
        data = args.histories.read_bytes()
        histories = read_histories(data.decode("utf-8-sig"))
        report = calibration_report(
            histories, data=str(args.histories), data_sha256=hashlib.sha256(data).hexdigest(), bins=args.bins,
            command=(COMMAND, hashlib.sha256(Path(__file__).read_bytes()).hexdigest()),
        )
    except OSError as error:
        print(f"Cannot read {args.histories}: {error.strerror or error}.", file=sys.stderr)
        return NOTHING
    except UnicodeDecodeError:
        print(f"Cannot read {args.histories}: it is not UTF-8 text.", file=sys.stderr)
        return NOTHING
    except HistoriesRefusedError as refused:
        print(refused, file=sys.stderr)
        return NOTHING
    for line in report.lines:
        print(line)
    return REPORTED


if __name__ == "__main__":
    sys.exit(main())
