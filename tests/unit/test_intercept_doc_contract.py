"""docs/intercept_engine.md documents the result and routes the code has.

Audit F-181. The documented result carried total_delta_v_km_s,
transfer_time_h and location_label, and burn components dv_along_track and
dv_cross_track; the code has total_delta_v_m_s and dv_prograde, dv_normal and
dv_radial, all in m/s. The documented routes /calculate and /tradespace do not
exist.
"""

from __future__ import annotations

import dataclasses
import re

from spectre.domain.models import BurnResult, InterceptResult
from tests.unit.test_deployment_contract import _repo_only


def _doc() -> str:
    return _repo_only("docs/intercept_engine.md").read_text(encoding="utf-8")


def _first_column_fields(section: str) -> list[str]:
    return re.findall(r"^\|\s*`(\w+)`\s*\|", section, re.M)


def test_every_documented_field_exists() -> None:
    doc = _doc()
    result = doc[doc.index("## Result Format"):doc.index("Each `BurnResult`")]
    burn = doc[doc.index("Each `BurnResult`"):doc.index("## Route Dispatch")]
    assert set(_first_column_fields(result)) == {f.name for f in dataclasses.fields(InterceptResult)}
    assert set(_first_column_fields(burn)) == {f.name for f in dataclasses.fields(BurnResult)}


def test_every_documented_route_exists() -> None:
    from spectre.web.routes.maneuver import router

    real = {(m, r.path) for r in router.routes for m in getattr(r, "methods", set())}
    documented = re.findall(r"`(GET|POST) (/plan/maneuver/[\w-]+)`", _doc())
    assert documented, "the doc names no routes"
    for method, path in documented:
        assert (method, path) in real, f"{method} {path} is not a route"
