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
    """Return ``{repo-relative path: {lines added or modified}}`` against *base*.

    Against the MERGE BASE and the WORKING TREE, not against HEAD.

    This read ``base...HEAD`` until 0.5.25, which compares COMMITS while the
    linter above reads the WORKING TREE. The two then disagree by exactly the
    number of lines the uncommitted edits add or remove, and every finding
    below the first such edit is scored against the wrong line. It shows up as
    four pre-existing smells appearing from nowhere, which is the harmless
    direction; the same offset silently moves a real finding OUT of scope,
    which is not. The artefact is built from the working tree, so the working
    tree is what has to be measured.
    """
    git_dir_check = _git("rev-parse", "--is-inside-work-tree").strip()
    if git_dir_check != "true":
        return {}

    # merge-base, so that commits landing on the base branch after this one
    # started do not read as this branch's work.
    try:
        anchor = _git("merge-base", base, "HEAD").strip() or base
    except subprocess.CalledProcessError:
        anchor = base

    changed: dict[str, set[int]] = {}
    path = ""
    for line in _git("diff", "-U0", anchor).splitlines():
        if line.startswith("+++ b/"):
            path = line[6:]
            changed.setdefault(path, set())
        elif path:
            match = _HUNK.match(line)
            if match:
                start = int(match.group(1))
                count = int(match.group(2) or 1)
                changed[path].update(range(start, start + count))

    # An untracked file is in no diff at all, so without this every finding in
    # a file added by this branch is dropped and the gate reports clean on code
    # it never looked at. A new file is entirely new code.
    for entry in _git("status", "--porcelain").splitlines():
        if not entry.startswith("?? "):
            continue
        candidate = Path(entry[3:].strip())
        for file in ([candidate] if candidate.is_file() else candidate.rglob("*.py")):
            if file.suffix == ".py":
                line_count = len(file.read_text(encoding="utf-8").splitlines())
                changed.setdefault(str(file), set()).update(range(1, line_count + 2))

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

    # Sort on (path, row) only. Sorting the raw tuples falls through to
    # comparing the finding dicts whenever two findings share a line, which
    # raises TypeError and takes the whole quality gate down with it.
    for path, row, finding in sorted(kept, key=lambda item: (item[0], item[1] or 0)):
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
