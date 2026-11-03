"""Threat Understanding on the sweep page, in shadow (SPC-166).

The sweep gathers what it holds about the red object, runs the model beside
the legacy verdict, and renders the range and Understanding under it. The
verdict badge and the worst case's sentence stay exactly as they were, and
the same inputs give the same ledger hash (I10).
"""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any

import pytest

from spectre.web.routes import threat
from tests.integration.test_pol_normality_panel import _history
from tests.integration.test_sweep_red_history import _stub_udl, _sweep, udl  # noqa: F401
from tests.integration.test_threat_sweep_routes import sweep_state  # noqa: F401


@pytest.fixture(autouse=True)
def _fixed(monkeypatch: pytest.MonkeyPatch) -> None:
    """No live burn watch, and the sweep's clock one hour after the history's newest set."""
    monkeypatch.setattr(threat, "start_watch", lambda *_a, **_k: None)
    newest = _history([25.0] * 7 + [150.0])[-1].epoch
    monkeypatch.setattr(threat, "_utc_now", lambda: newest + timedelta(hours=1))


def _badge(page: str) -> str:
    found = re.search(r'<span class="spectre-band-badge[^"]*">[^<]*</span>', page)
    assert found is not None
    return found.group(0)


def _hash(page: str) -> str:
    found = re.search(r"Ledger hash ([0-9a-f]{16})", page)
    assert found is not None
    return found.group(1)


class TestTheShadowIsOnTheSweep:
    def test_the_threat_and_understanding_lines_and_a_collapsed_ledger(
        self, client: Any, auth_cookie: str, udl: Any, monkeypatch: pytest.MonkeyPatch,  # noqa: F811
    ) -> None:
        _stub_udl(monkeypatch, [25.0] * 7 + [150.0])
        page = _sweep(client, auth_cookie)
        assert 'class="threat-understanding"' in page
        assert re.search(r"Threat: (assessed|cannot assess)", page)
        assert re.search(r"Understanding (LOW|MODERATE|HIGH)\. ", page)
        assert re.search(r"<details class=\"tu-ledger\"[^>]*>", page)
        assert "latest burn, unprecedented" in page

    def test_the_same_inputs_give_the_same_ledger_hash(
        self, client: Any, auth_cookie: str, udl: Any, monkeypatch: pytest.MonkeyPatch,  # noqa: F811
    ) -> None:
        _stub_udl(monkeypatch, [25.0] * 7 + [150.0])
        first = _hash(_sweep(client, auth_cookie))
        assert _hash(_sweep(client, auth_cookie)) == first

    def test_the_verdict_badge_and_sentence_are_as_without_it(
        self, client: Any, auth_cookie: str, udl: Any, monkeypatch: pytest.MonkeyPatch,  # noqa: F811
    ) -> None:
        _stub_udl(monkeypatch, [25.0] * 7 + [150.0])
        shown = _sweep(client, auth_cookie)
        monkeypatch.setattr(threat, "_with_understanding", lambda worst, _u: worst)
        without = _sweep(client, auth_cookie)
        assert 'class="threat-understanding"' not in without
        assert _badge(shown) == _badge(without)
        summary = re.search(r"Least warning: [^<]*", without)
        assert summary is not None and summary.group(0) in shown
