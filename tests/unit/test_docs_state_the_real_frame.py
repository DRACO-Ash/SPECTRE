"""The docs name the frame the code works in.

Audit F-055. README.md declared ICRF/J2000, but SGP4 states are TEME and no
TEME-to-J2000/GCRF conversion exists in spectre/; the same line gave speeds
in km/s while results carry delta-V in m/s.
"""

from __future__ import annotations

import re

from tests.unit.test_deployment_contract import _REPO_ROOT, _repo_only

_DOCS = ("README.md", "docs/architecture.md", "docs/intercept_engine.md", "docs/spectre_deep_dive.md")


def _has_gcrf_transform() -> bool:
    return any(
        re.search(r"def\s+\w*(teme\w*(gcrf|j2000|icrf)|(gcrf|j2000|icrf)\w*teme)\w*", p.read_text(encoding="utf-8"), re.I)
        for p in (_REPO_ROOT / "spectre" / "astro").glob("*.py")
    )


def test_no_doc_claims_a_frame_the_code_never_reaches() -> None:
    if _has_gcrf_transform():
        return
    # A line saying states are NOT converted is the correction, not the claim.
    offenders = [
        f"{name}: {line.strip()}"
        for name in _DOCS
        for line in _repo_only(name).read_text(encoding="utf-8").splitlines()
        if re.search(r"\b(J2000|ICRF)\b", line) and not re.search(r"\bnot\b", line)
    ]
    assert not offenders, f"these name a frame no code converts to: {offenders}"


def test_the_readme_states_teme_and_delta_v_units() -> None:
    readme = _repo_only("README.md").read_text(encoding="utf-8")
    assert "TEME" in readme
    assert re.search(r"delta-V[^.\n]*m/s", readme, re.I)
