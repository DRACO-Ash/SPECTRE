"""Every number field the decision panel gives a value starts at a value the browser accepts.

A number field whose value is off its step fails the browser's check, and htmx checks the form before it posts,
so pressing Evaluate with the panel's own defaults posted nothing: the response row's time to execute started at
6 h with a minimum of 0.1 h and a step of 0.5 h, whose nearest valid values are 5.6 and 6.1. This holds for the
rows the panel renders and for the rows its Add buttons add.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from tests.integration.test_decision_hypothesis_panel import _panel

_NUMBER = re.compile(r'<input type="number"[^>]*>')


def _attr(field: str, name: str) -> str | None:
    match = re.search(rf'\b{name}="([^"]*)"', field)
    return None if match is None else match.group(1)


def _off_step(field: str) -> str | None:
    """Why *field*'s literal value fails the browser's check, or None when it passes or states no literal value."""
    value, low, high, step = (_attr(field, k) for k in ("value", "min", "max", "step"))
    literal = re.compile(r"-?\d+(\.\d+)?")
    if value is None or not literal.fullmatch(value):
        return None
    v = Decimal(value)
    if low is not None and literal.fullmatch(low) and v < Decimal(low):
        return f"{field}: below its minimum"
    if high is not None and literal.fullmatch(high) and v > Decimal(high):
        return f"{field}: above its maximum"
    if step is None or step == "any":
        return None
    base = Decimal(low) if low is not None and literal.fullmatch(low) else Decimal(0)
    return None if (v - base) % Decimal(step) == 0 else f"{field}: off its step"


def test_every_default_number_is_one_the_browser_accepts(client: Any, auth_cookie: str) -> None:
    fields = _NUMBER.findall(_panel(client, auth_cookie))
    assert any('name="fr_time"' in f for f in fields)
    assert [why for why in map(_off_step, fields) if why is not None] == []
