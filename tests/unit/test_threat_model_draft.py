"""The engine's draft threat model covers what evaluation finding F-08 asked for, and says it is a draft (SPC-199).

It is a document for the owner's security lead to review and sign, so what is held here is its shape: the 7
ISN 2023/09 principles, the threats the brief named, a path, a remainder and an owner for each, the house style,
and a plain statement that it is unsigned and does not close gate G9.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_DOC = _ROOT / "docs" / "threat-model-decision-engine.md"

_PRINCIPLES = (
    "Understand and Define Context",
    "Plan the Security Activities",
    "Implement Continuous Risk Management",
    "Define Security Controls",
    "Engage and Manage the Supply Chain",
    "Assure, Verify and Test",
    "Enable Through Life Management",
)


def _text() -> str:
    return _DOC.read_text(encoding="utf-8")


def _register_rows() -> list[list[str]]:
    rows = [line for line in _text().splitlines() if re.match(r"\| T\d+ \|", line)]
    return [[cell.strip() for cell in row.strip("|").split("|")] for row in rows]


def test_it_says_it_is_an_unsigned_draft_that_does_not_close_g9() -> None:
    head = _text()[:800]
    assert "DRAFT" in head
    assert "not signed" in head
    assert "does not close" in head and "G9" in head


@pytest.mark.parametrize("principle", _PRINCIPLES)
def test_it_is_structured_by_each_principle(principle: str) -> None:
    assert re.search(rf"^### \d\. {re.escape(principle)}$", _text(), re.M), principle


@pytest.mark.parametrize("subject", [
    "Poisoned or corrupted element sets",
    "Tampered weights, rule, vetoes",
    "Tampered priors",
    "Integrity of decision records and stored inputs",
    "Non-repudiation",
    "friendly priorities",
    "The UDL credential",
    "Browser-side injection",
])
def test_it_covers_each_threat_the_brief_named(subject: str) -> None:
    assert [row for row in _register_rows() if subject in row[1]], subject


def test_each_threat_names_a_path_a_remainder_and_its_owner() -> None:
    rows = _register_rows()
    assert len(rows) >= 8
    for row in rows:
        assert len(row) == 5, row[0]
        assert "`" in row[2], f"{row[0]} names no path for what exists"
        assert row[3], f"{row[0]} says nothing remains"
        assert row[4] == "The owner's security lead", row[0]


def test_it_cites_the_controls_it_builds_on() -> None:
    text = _text()
    for cited in ("SPC-201", "SPC-192", "SPC-193", "SPC-199", "audit/ARCHITECTURE.md` section 3.4",
                  "`spectre/web/app.py`"):
        assert cited in text, cited


def test_it_follows_the_house_style() -> None:
    text = _text()
    assert "—" not in text and "--" not in text, "no long dashes or double dashes"
    assert not re.search(r"^\s*[-*] ", text, re.M), "bullets are filled circles or squares"
    assert not re.search(r"^\s*(---|\*\*\*|___)\s*$", text, re.M), "no horizontal rules"


def test_it_names_the_commit_its_controls_were_read_at() -> None:
    assert re.search(r"\*\*Basis\.\*\*[^#]*`adeb112`", _text())


def _row(threat: str) -> list[str]:
    return next(row for row in _register_rows() if row[0] == threat)


def test_browser_injection_names_the_markup_the_policy_does_not_stop() -> None:
    """Injected htmx attributes send requests with the inherited CSRF token under the strict policy (review of
    SPC-199), so the gap is named rather than the policy read as closing the class."""
    remains = _row("T9")[3]
    assert "hx-get" in remains and "CSRF token" in remains and "hx-headers" in remains
    assert "data-init" in remains


def test_exhaustion_cites_the_one_slot_that_exists() -> None:
    exists, remains = _row("T11")[2:4]
    assert "`spectre/web/decision_job.py`" in exists
    assert "No limit across operators on evaluations running at once" not in remains


def test_the_scope_and_supply_chain_say_what_the_code_does() -> None:
    assert "a GET, to UDL or to GCAT" in _text()
    assert "pip dependencies and the workflow actions" in _row("T10")[2]
