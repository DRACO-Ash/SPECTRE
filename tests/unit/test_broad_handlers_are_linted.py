"""Broad exception handlers are checked by the CI lint, not by convention.

Audit F-065. The CI ruff selection was E, F, I, UP, B and SIM, so 52 ``noqa``
directives named rules nobody ran and every ``except Exception`` in product
code went unflagged. BLE and S110 are now selected, RUF100 catches directives
that suppress nothing, and the handlers that caught everything around element
set parsing catch what that parsing actually raises.
"""

from __future__ import annotations

import contextlib
import tomllib
from datetime import UTC, datetime

import pytest

from spectre.astro.propagator import TLE_ERRORS, TLEOrbit, regime_from_tle
from tests.unit.test_deployment_contract import _repo_only

_GOOD = (
    "1 25544U 98067A   26290.50000000  .00016717  00000-0  10270-3 0  9005\n"
    "2 25544  51.6400 208.9163 0006317  69.9862  25.2906 15.49541392 10001"
)


def test_ci_lint_selects_the_broad_handler_rules() -> None:
    lint = tomllib.loads(_repo_only("pyproject.toml").read_text(encoding="utf-8"))["tool"]["ruff"]["lint"]
    for rule in ("BLE", "S110", "RUF100"):
        assert rule in lint["select"], f"{rule} is not selected"


@pytest.mark.parametrize("tle", [
    "",
    "not an element set",
    _GOOD.replace("15.49541392", "00.00000000"),
    _GOOD.replace("51.6400", "5x.6400"),
    _GOOD.replace("0006317", "9999999"),
])
def test_a_bad_element_set_raises_only_what_the_handlers_catch(tle: str) -> None:
    for step in (lambda: TLEOrbit(tle).propagate(datetime(2026, 10, 24, tzinfo=UTC)), lambda: regime_from_tle(tle)):
        with contextlib.suppress(TLE_ERRORS):   # anything else escapes and fails the test
            step()


def test_a_notso_record_normalises_from_either_field_name() -> None:
    from spectre.web.routes.udl import _normalise_notso

    assert _normalise_notso({"id": 7, "date": "2026-10-24", "messageId": ""}) == {
        "message_id": "7", "issue_date": "2026-10-24", "start": "", "end": "",
        "type": "", "description": "", "raw": "",
    }
    assert _normalise_notso({"rawMessage": "a", "message": "b"})["raw"] == "a"
