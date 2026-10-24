"""A sweep method that refuses is reported, with its reason.

Audit F-058. The July 2026 fix records why each sweep method produced nothing,
because refusals cluster on the fast, aggressive end and dropping them biased
the sweep towards under-reporting the quickest approaches. Nothing pinned it:
putting the bare ``pass`` back left the suite green. This drives the fan-out
with a solver that raises and follows the reason through to the panel.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from spectre.domain.models import ThreatTarget
from spectre.web.routes import threat
from tests.unit import test_threat_sweep_template as sweep


def _degenerate(**_kwargs: Any) -> Any:
    raise ValueError("Transfer angle within 0.5 degrees of 180. Geometry is degenerate")


def test_the_refusal_reaches_the_rendered_panel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(threat, "_SWEEP_METHODS", (("lambert", _degenerate, {}),))
    request = threat._SweepRequest(
        red_tle="RED", target_tle="BLUE", target=ThreatTarget("SKYNET-5A", "30793", "hrr", 1),
        max_dv_m_s=500.0, regime="GEO",
    )
    refusals: dict[str, str] = {}
    entries = threat._sweep_all_methods(request, [("now", datetime(2026, 9, 13, tzinfo=UTC))], refusals)

    assert entries == []
    assert refusals == {"lambert": "Transfer angle within 0.5 degrees of 180"}
    html = sweep._render(sweep._context(method_refusals=sorted(refusals.items())))
    assert "1 method(s) produced no solution" in html
    assert "Transfer angle within 0.5 degrees of 180" in html


@pytest.mark.parametrize(
    ("message", "shown"),
    [
        ("degenerate Lambert geometry: transfer angle 179.9876 deg is within 0.5 deg of 180. Try another epoch",
         "degenerate Lambert geometry: transfer angle 179.9876 deg is within 0.5 deg of 180"),
        ("No intercept within the 0.500 km/s budget; widen it", "No intercept within the 0.500 km/s budget"),
        ("ends with a full stop.", "ends with a full stop"),
    ],
)
def test_a_reason_keeps_its_figures(message: str, shown: str) -> None:
    """Only a full stop before whitespace ends the sentence, not a decimal point."""
    assert threat._refusal_reason(ValueError(message)) == shown
