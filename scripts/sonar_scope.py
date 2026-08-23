"""Filter static-analysis findings to the lines the quality gate actually scores.

SonarQube's gate conditions apply to NEW and CHANGED code. Linters report on
whole files, so a pre-existing smell in a file you touched would otherwise look
like a new violation and send you refactoring code your change never went near.
This reads ruff's JSON output on stdin and keeps only findings that land on a
line added or modified against the base branch, which is the scope the gate uses.

Usage:  ruff check --output-format=json ... | python3 scripts/sonar_scope.py [base]
Exit:   0 when no finding lands on changed code, 1 otherwise.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def _git(*args: str) -> str:
    """Run a git command and return its stdout."""
    return subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        capture_output=True, text=True, check=True,
    ).stdout


def changed_lines(base: str) -> dict[str, set[int]]:
    """Return ``{repo-relative path: {lines added or modified}}`` against *base*."""
    changed: dict[str, set[int]] = {}
    path = ""
    for line in _git("diff", "-U0", f"{base}...HEAD").splitlines():
        if line.startswith("+++ b/"):
            path = line[6:]
            changed.setdefault(path, set())
        elif path:
            match = _HUNK.match(line)
            if match:
                start = int(match.group(1))
                count = int(match.group(2) or 1)
                changed[path].update(range(start, start + count))
    return changed


def _relative(filename: str, repo_root: Path) -> str:
    """Return *filename* relative to the repository root."""
    try:
        return str(Path(filename).resolve().relative_to(repo_root))
    except ValueError:
        return filename


def main() -> int:
    base = sys.argv[1] if len(sys.argv) > 1 else "master"
    findings = json.load(sys.stdin)
    scoped = changed_lines(base)
    repo_root = Path(_git("rev-parse", "--show-toplevel").strip())

    kept = []
    for finding in findings:
        path = _relative(finding.get("filename", ""), repo_root)
        row = finding.get("location", {}).get("row")
        if row in scoped.get(path, set()):
            kept.append((path, row, finding))

    for path, row, finding in sorted(kept):
        code = finding.get("code") or "?"
        print(f"  {path}:{row}  {code}  {finding.get('message')}")

    total = len(findings)
    print(
        f"\n  {len(kept)} finding(s) on changed lines "
        f"({total} total across the touched files, the rest pre-existing)."
    )
    return 1 if kept else 0


if __name__ == "__main__":
    sys.exit(main())
