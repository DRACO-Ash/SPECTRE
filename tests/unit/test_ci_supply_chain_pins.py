"""CI runs only what it has pinned and checked.

Audit F-175. Every action was pinned by a mutable tag, the gitleaks binary was
downloaded and executed with no checksum, and the quality job fetched
``jscpd@4`` at whatever 4.x was current.
"""

from __future__ import annotations

import re

from tests.unit.test_deployment_contract import _REPO_ROOT, _repo_only

_USES = re.compile(r"^\s*(?:-\s*)?uses:\s*(\S+)", re.M)


def _workflows() -> list[tuple[str, str]]:
    _repo_only(".github/workflows")
    return [(p.name, p.read_text(encoding="utf-8")) for p in sorted((_REPO_ROOT / ".github" / "workflows").glob("*.y*ml"))]


def test_every_action_is_pinned_to_a_commit() -> None:
    for name, text in _workflows():
        for ref in _USES.findall(text):
            if ref.startswith("./"):
                continue
            assert re.search(r"@[0-9a-f]{40}$", ref), f"{name}: {ref} is not pinned to a commit"


def test_no_download_is_piped_straight_into_an_archive() -> None:
    for name, text in _workflows():
        joined = re.sub(r"\\\n\s*", " ", text)
        assert not re.search(r"curl[^\n|]*\|\s*tar", joined), f"{name}: curl piped into tar"
        if "curl" in joined and "releases/download" in joined:
            assert "sha256sum -c" in joined, f"{name}: a release download is never checked"


def test_jscpd_is_an_exact_version() -> None:
    text = _repo_only("scripts/check-quality.sh").read_text(encoding="utf-8")
    assert re.search(r"jscpd@\d+\.\d+\.\d+\b", text)
    assert not re.search(r"jscpd@\d+\s", text)
