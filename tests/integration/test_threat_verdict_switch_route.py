"""The verdict switch on the sweep page (SPC-175).

Off, which is how every shipped configuration leaves it, the sweep shows the
current rule's verdict and no reason line. On, the badge reads concept
section 4.8's verdict and the line under it says why and what the current
rule reads. The Threat range, Understanding and the ledger hash are the same
either way: the switch changes what is shown, never what was assessed.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from spectre.domain.threat_assessment import AccessEvidence, Band
from spectre.web.routes import threat
from tests.integration.test_sweep_red_history import _sweep, udl  # noqa: F401
from tests.integration.test_threat_sweep_routes import sweep_state  # noqa: F401

_ENV = "SPECTRE_THREAT_VERDICT_SWITCH"


@pytest.fixture(autouse=True)
def _no_watch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(threat, "start_watch", lambda *_a, **_k: None)


def _badge(page: str) -> str:
    found = re.search(r'<span class="spectre-band-badge[^"]*">[^<]*</span>', page)
    assert found is not None
    return found.group(0)


def _hash(page: str) -> str:
    found = re.search(r"Ledger hash ([0-9a-f]{16})", page)
    assert found is not None
    return found.group(1)


class TestTheSwitchOnTheSweep:
    def test_off_no_reason_line_and_on_the_badge_reads_the_new_verdict_with_its_reason(
        self, client: Any, auth_cookie: str, sweep_state: Any, monkeypatch: pytest.MonkeyPatch,  # noqa: F811
    ) -> None:
        # A cheap geometry (ACCESS CRITICAL) against an object assessed MEDIUM, with no history held: the current
        # rule reads MEDIUM and Understanding is LOW, so section 4.8 reads the access ceiling.
        monkeypatch.setattr(AccessEvidence, "band", lambda _self: Band.CRITICAL)
        monkeypatch.setattr(threat, "get_intel", lambda _s: {"threat_level": "MEDIUM"})
        monkeypatch.delenv(_ENV, raising=False)
        off = _sweep(client, auth_cookie)
        monkeypatch.setenv(_ENV, "true")
        on = _sweep(client, auth_cookie)
        assert 'class="verdict-switch"' not in off
        assert "MEDIUM THREAT" in _badge(off)
        reason = re.search(r'<div class="verdict-switch">([^<]*)</div>', on)
        assert reason is not None
        assert reason.group(1).strip().startswith("Understanding LOW. Threat reads its ceiling")
        assert reason.group(1).strip().endswith("The current rule reads Threat MEDIUM.")
        assert "CRITICAL THREAT" in _badge(on)
        assert _hash(on) == _hash(off)
