"""A document git refuses to track reaches nobody.

``.gitignore`` carried ``docs/*``. All 24 files in ``docs/`` survive only
because they predate it; the rule was hiding exactly one file, the next
assessment someone wrote, and it vanished without a word.

This is the second time the same defect has shipped. Release 0.5.18 found an
unanchored ``data/`` swallowing ``spectre/data/`` by the identical mechanism:
a directory rule that looks harmless because everything inside it was
committed before the rule existed. Both are pinned now.

Five ``!docs/*.ext`` negations were already sitting at the top of the file,
someone's earlier attempt at this fix. They never worked, because gitignore
applies the LAST matching rule and ``docs/*`` came afterwards. A negation that
is written before the rule it is meant to negate is not a fix, it is a comment
that looks like one, which is why this is a test and not a tidier .gitignore.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def _is_ignored(relative_path: str) -> bool:
    return subprocess.run(  # noqa: S603
        ["git", "check-ignore", "-q", relative_path],
        cwd=_ROOT, capture_output=True, text=True, check=False,
    ).returncode == 0


class TestDocsCanBeCommitted:
    def test_a_new_document_is_not_ignored(self) -> None:
        """The general rule, not just the documents that happen to be here."""
        probe = _ROOT / "docs" / "_ignore_probe.md"
        probe.parent.mkdir(exist_ok=True)
        probe.write_text("", encoding="utf-8")
        try:
            assert not _is_ignored("docs/_ignore_probe.md"), (
                "a new document under docs/ is gitignored, so it can never be "
                "committed and nobody but its author will ever read it. "
                "Remove whatever rule matches it; git check-ignore -v names "
                "the file and line."
            )
        finally:
            probe.unlink(missing_ok=True)

    def test_every_document_already_here_stays_trackable(self) -> None:
        """A rule added later must not orphan what is already committed."""
        tracked = subprocess.run(  # noqa: S603
            ["git", "ls-files", "docs/"],
            cwd=_ROOT, capture_output=True, text=True, check=False,
        ).stdout.split()
        assert tracked, "docs/ should contain tracked files"
        orphaned = [f for f in tracked if _is_ignored(f)]
        assert not orphaned, (
            f"{len(orphaned)} tracked documents are now gitignored: {orphaned[:5]}. "
            "They survive only until someone needs to change one."
        )

    def test_the_packaged_ledger_is_trackable(self) -> None:
        """scripts/package-appstore.sh reads it, so a build from a fresh clone
        fails outright if it is ever ignored."""
        assert not _is_ignored("docs/CHANGE-LEDGER.md"), (
            "docs/CHANGE-LEDGER.md is gitignored. package-appstore.sh requires "
            "it, so a build from a fresh clone would fail."
        )


class TestDocsStillDoNotShip:
    """Making documents committable must not put them in the artefact."""

    def test_the_image_excludes_docs(self) -> None:
        dockerignore = (_ROOT / ".dockerignore").read_text(encoding="utf-8")
        assert any(line.strip() in ("docs/", "docs") for line in dockerignore.splitlines()), (
            "docs/ is no longer excluded from the runtime image"
        )

    def test_the_packager_strips_docs(self) -> None:
        packager = (_ROOT / "scripts" / "package-appstore.sh").read_text(encoding="utf-8")
        assert "$STAGE/docs" in packager, (
            "the packager no longer removes docs/ from the staging tree"
        )

    def test_sonar_does_not_analyse_docs(self) -> None:
        props = (_ROOT / "sonar-project.properties").read_text(encoding="utf-8")
        sources = [ln.split("=", 1)[1].strip() for ln in props.splitlines()
                   if ln.startswith("sonar.sources=")]
        assert sources, "sonar.sources must be declared"
        assert "docs" not in sources[0].split(","), (
            "docs/ is in sonar.sources and would be analysed as application code"
        )
