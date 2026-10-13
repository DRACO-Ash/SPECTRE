"""No figure the operator reads is in kilometres per second.

The conversion from km/s to m/s touched 42 files. Four sites were missed on the
first pass and each failed silently rather than loudly:

  * the delta-v budget bar divided by a hardcoded 3.0 and captioned itself
    "% of 3 km/s", so it misreported the moment anyone changed the budget;
  * the sweep's row colouring banded on 0.5 and 1.0, which against m/s values
    shades every row above 1 m/s identically;
  * the intercept panel banded CRITICAL at 2.0, which against m/s values makes
    almost every intercept critical;
  * the trade-space chart labelled its axis km/s while plotting m/s.

None of them raised. All of them put a wrong number in front of an operator.
This file is the guard: it reads the shipped templates and route modules and
fails if km/s reaches a screen.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader, StrictUndefined

_ROOT = Path(__file__).resolve().parents[2]
_TEMPLATES = _ROOT / "spectre" / "web" / "templates"
_ROUTES = _ROOT / "spectre" / "web" / "routes"

#: Everywhere outside the astro package that can render a velocity. The first
#: version of this guard scanned only web/routes, which left domain/ and
#: training/ unchecked.
_NON_ASTRO_PY = [
    _ROOT / "spectre" / "web" / "routes",
    _ROOT / "spectre" / "domain",
    _ROOT / "spectre" / "web",
]

#: Attributes that hold km/s because they come straight from the astro package.
#: A template that labels one of these m/s MUST also scale it, and a guard that
#: only greps for the string "km/s" cannot tell the difference: relabelling
#: without converting removes the very string the grep looks for.
#:
#: This is not hypothetical. The Hill-frame burn state in
#: partials/intercept_geometry.html was relabelled from km/s to m/s with no
#: conversion, printing a number a thousand times too small under the new
#: label, and the string-based check went green because the file no longer
#: contained "km/s".
_KM_S_ATTRIBUTES: tuple[str, ...] = (
    "burn_state.xd", "burn_state.yd", "burn_state.zd",
    "delta_v_km_s", "predicted_delta_v_km_s", "total_delta_v",
    "dv_stats.mean", "dv_stats.std", "dv_stats.p95",
    "dv_stats.low_2sigma", "dv_stats.high_2sigma",
)

#: The one deliberate exception, with its reason.
#:
#: An orbital state vector's velocity is not a manoeuvre cost. It runs about
#: 7.6 km/s in low Earth orbit and 3.07 km/s at geostationary, and the
#: assessment this calibration is drawn from writes orbital speed in km/s and
#: manoeuvre cost in m/s throughout. Rendering a state vector as 7,600 m/s
#: would depart from the source and from the convention every analyst reads.
_ALLOWED_KM_S_TEMPLATES: dict[str, str] = {
    "partials/statevector_fields.html":
        "orbital state vector velocity, not a manoeuvre cost",
}


#: Jinja and HTML comments never reach the rendered page, so a km/s inside one
#: is documentation of the change, not a figure an operator reads. They are
#: stripped BEFORE scanning rather than skipped line by line, because a
#: multi-line comment's continuation lines do not start with the opening token.
_COMMENT = re.compile(r"\{#.*?#\}|<!--.*?-->", re.DOTALL)


def _templates() -> list[Path]:
    return sorted(_TEMPLATES.rglob("*.html"))


def _rendered_lines(path: Path) -> list[tuple[int, str]]:
    """Lines of *path* with comment bodies blanked, numbering preserved."""
    text = path.read_text(encoding="utf-8")
    # Replace each comment with the same number of newlines so line numbers
    # in a failure message still point at the real file.
    blanked = _COMMENT.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    return list(enumerate(blanked.splitlines(), 1))


class TestNoTemplateShowsKilometresPerSecond:
    def test_every_template_is_either_clean_or_explicitly_excused(self) -> None:
        offenders: list[str] = []
        for path in _templates():
            rel = path.relative_to(_TEMPLATES).as_posix()
            if rel in _ALLOWED_KM_S_TEMPLATES:
                continue
            for i, line in _rendered_lines(path):
                if "km/s" in line:
                    offenders.append(f"{rel}:{i}: {line.strip()[:110]}")
        assert not offenders, (
            "these templates put km/s in front of an operator:\n  "
            + "\n  ".join(offenders)
        )

    def test_the_excuse_list_has_not_rotted(self) -> None:
        """An allow-list entry that no longer applies is a licence, not a note."""
        for rel, reason in _ALLOWED_KM_S_TEMPLATES.items():
            path = _TEMPLATES / rel
            assert path.exists(), f"{rel} is excused but no longer exists"
            assert "km/s" in path.read_text(encoding="utf-8"), (
                f"{rel} is excused for '{reason}' but no longer contains km/s; "
                "remove the entry rather than leaving a standing exemption"
            )


class TestNoRouteFormatsKilometresPerSecond:
    """A km/s label in an f-string reaches the operator just as surely."""

    #: km/s inside a comment or docstring is documentation of the boundary and
    #: is expected. Only rendered strings are in scope.
    _RENDERED = re.compile(r'f"[^"]*km/s|f\'[^\']*km/s')

    def test_no_route_renders_a_km_s_label(self) -> None:
        offenders: list[str] = []
        for directory in _NON_ASTRO_PY:
            for path in sorted(directory.glob("*.py")):
                for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                    if self._RENDERED.search(line):
                        offenders.append(f"{path.name}:{i}: {line.strip()[:110]}")
        assert not offenders, (
            "these routes format a km/s label into operator-facing text:\n  "
            + "\n  ".join(offenders)
        )


class TestNoTemplatePerformsUnitArithmetic:
    """The invariant that makes a double conversion structurally impossible.

    Templates used to scale km/s to m/s inline in eighteen places across four
    files. Every one was correct. Together they were a trap, because the route
    layer converts at its boundary too: the first person to finish the job by
    converting a result object at the boundary would have left the template
    scaling an already-converted value. In the pattern-of-life panel that would
    have put the charts at 1,000,000x and the table at 1,000x, side by side,
    both rendering without error and neither raising.

    The rule that removes it is one a reader can hold: a template receives
    figures already in the unit of their name and never does the sum itself.
    Conversion lives in Python, at a named route boundary, where it is one
    greppable call and one place to get right.
    """

    def test_no_template_scales_by_a_thousand(self) -> None:
        scaling = re.compile(r"[*/]\s*1000(?:\.0+)?\b")
        offenders: list[str] = []
        for path in _templates():
            rel = path.relative_to(_TEMPLATES).as_posix()
            for i, line in _rendered_lines(path):
                if scaling.search(line):
                    offenders.append(f"{rel}:{i}: {line.strip()[:110]}")
        assert not offenders, (
            "a template is converting units. Move it to the route boundary and "
            "pass the figure in already in m/s, so the conversion cannot happen "
            "twice:\n  " + "\n  ".join(offenders)
        )

    def test_the_conversion_helper_is_what_routes_use(self) -> None:
        """One function, so there is one place to be wrong."""
        from spectre.web.format_units import to_m_s

        assert to_m_s(0.0601) == pytest.approx(60.1)
        assert to_m_s(None) is None, (
            "a missing figure must pass through; a template rendering '-' "
            "should not have to guard the conversion as well"
        )


class TestRelabellingIsNotConverting:
    """Changing the unit on the label without changing the number is 1000x wrong."""

    def test_every_km_s_attribute_shown_as_m_s_is_scaled(self) -> None:
        offenders: list[str] = []
        for path in _templates():
            rel = path.relative_to(_TEMPLATES).as_posix()
            for i, line in _rendered_lines(path):
                if "m/s" not in line:
                    continue
                # Anchored so "total_delta_v" does not match the already
                # converted "total_delta_v_m_s".
                named = [
                    a for a in _KM_S_ATTRIBUTES
                    if re.search(re.escape(a) + r"(?!\w)", line)
                ]
                if not named:
                    continue
                if re.search(r"\*\s*1000(?:\.0+)?\b", line):
                    continue
                offenders.append(f"{rel}:{i}: {', '.join(named)} -> {line.strip()[:90]}")
        assert not offenders, (
            "these lines label a km/s value as m/s without scaling it, so the "
            "number shown is a thousand times too small:\n  " + "\n  ".join(offenders)
        )


class TestTheConversionHappensExactlyOnce:
    """A second conversion is a value out by a factor of a million."""

    def test_no_route_multiplies_a_metres_per_second_field_by_a_thousand(self) -> None:
        pattern = re.compile(r"delta_v_m_s\s*\*\s*1000|_m_s\s*\*\s*1000\b")
        offenders: list[str] = []
        for path in sorted(_ROUTES.glob("*.py")):
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if pattern.search(line):
                    offenders.append(f"{path.name}:{i}: {line.strip()[:110]}")
        assert not offenders, (
            "a field already in m/s is being scaled again:\n  " + "\n  ".join(offenders)
        )

    def test_no_template_multiplies_a_metres_per_second_field_by_a_thousand(self) -> None:
        pattern = re.compile(r"delta_v_m_s\s*\*\s*1000|_m_s\s*\*\s*1000\b")
        offenders: list[str] = []
        for path in _templates():
            rel = path.relative_to(_TEMPLATES).as_posix()
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if pattern.search(line):
                    offenders.append(f"{rel}:{i}: {line.strip()[:110]}")
        assert not offenders, (
            "a field already in m/s is being scaled again in a template:\n  "
            + "\n  ".join(offenders)
        )

    def test_every_thousand_scaling_in_the_web_layer_names_its_km_side(self) -> None:
        """The invariant that catches a conversion a name-based check misses.

        The first version of this guard looked for ``delta_v_m_s * 1000``. It
        did not catch ``b_dv = burn.delta_v_m_s`` followed by
        ``b_dv_ms = b_dv * 1000.0``, nor ``f"{dv * 1000:.1f} m/s"``, because
        both scale a LOCAL name. Both were live, both put a figure a thousand
        times too large in front of an operator.

        The web layer should never scale a velocity except when crossing into
        or out of the astro package, and every such crossing names km
        somewhere on the line. Anything else is an undeclared conversion.
        """
        scaling = re.compile(r"[*/]\s*1000(?:\.0+)?\b")
        offenders: list[str] = []
        for path in sorted(_ROUTES.glob("*.py")):
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if not scaling.search(line):
                    continue
                if "km" in line.lower():
                    continue
                offenders.append(f"{path.name}:{i}: {line.strip()[:110]}")
        assert not offenders, (
            "these lines scale by 1000 without naming the km/s side, so it is "
            "impossible to tell a boundary conversion from a bug:\n  "
            + "\n  ".join(offenders)
        )

    def test_the_astro_package_still_speaks_km_s(self) -> None:
        """The physics layer must NOT have been converted.

        MU_EARTH is in km^3/s^2 and SGP4 returns km and km/s. Renaming astro
        fields to _m_s while they hold km/s values produced, on the first
        attempt at this change, the line ``dv_m_s = delta_v_m_s * 1000.0``
        and a docstring reading ``delta_v_m_s: Total delta-V (km/s)``.
        """
        astro = _ROOT / "spectre" / "astro"
        offenders: list[str] = []
        for path in sorted(astro.glob("*.py")):
            text = path.read_text(encoding="utf-8")
            for i, line in enumerate(text.splitlines(), 1):
                if re.search(r"^\s*(total_)?delta_v_m_s\s*[:=]", line):
                    offenders.append(f"{path.name}:{i}: {line.strip()[:110]}")
        assert not offenders, (
            "the astro package computes in km/s and must keep those names:\n  "
            + "\n  ".join(offenders)
        )


class TestTheWrittenMaterialMatchesTheInterface:
    """An operator reads more than the screen."""

    def test_training_scenarios_state_delta_v_in_m_s(self) -> None:
        """These carry GRADED answers, so a stale unit marks a right answer wrong."""
        path = _ROOT / "spectre" / "training" / "config" / "scenarios.yaml"
        offenders = [
            f"{i}: {line.strip()[:100]}"
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
            if "km/s" in line
        ]
        assert not offenders, (
            "training briefings and graded answers still state km/s:\n  "
            + "\n  ".join(offenders)
        )

    def test_the_operator_guide_generator_states_m_s(self) -> None:
        """The guide is the only written description of the units."""
        path = _ROOT / "docs" / "generate_guide.py"
        if not path.exists():
            pytest.skip("operator guide generator not present in this checkout")
        offenders = [
            f"{i}: {line.strip()[:100]}"
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
            if "km/s" in line
        ]
        assert not offenders, (
            "the operator guide still documents km/s:\n  " + "\n  ".join(offenders)
        )


class TestTheDisplayFilterIsRegistered:
    def test_the_app_environment_has_the_m_s_filter(self) -> None:
        """Templates use ``| m_s``; an unregistered filter is a 500, not a typo."""
        from spectre.web.app import templates

        assert "m_s" in templates.env.filters

    @pytest.mark.parametrize(
        ("value", "expected"),
        [(0.03, "0.03"), (5.25, "5.2"), (11.0, "11"), (182.3, "182"), (None, "-")],
    )
    def test_it_rounds_without_claiming_precision_we_lack(
        self, value: float | None, expected: str
    ) -> None:
        from spectre.web.format_units import format_m_s

        assert format_m_s(value) == expected


class TestThePatternOfLifeTrapIsClosed:
    """The specific hazard this file was extended to remove.

    ``pol_results.html`` converted km/s to m/s in twelve places while
    ``pol.py`` converted at its own boundary. Both were correct, and that was
    the problem: converting ``PatternOfLifeResult`` at the boundary, the
    obvious next step, would have left the template scaling an already
    converted value. The charts would have gone to 1,000,000x and the table to
    1,000x in the same panel, with no error anywhere.

    Two things close it. The template no longer references a km/s field at all,
    so a boundary conversion cannot reach it; and the one function that does
    convert is pinned to exactly one factor of a thousand.
    """

    #: Velocity-bearing attributes on the astro pattern-of-life objects. A
    #: template that reads one of these is reading km/s and must be converting,
    #: which is what this class exists to prevent.
    _KM_S_FIELDS = (
        "total_dv_km_s", "dv_threshold_km_s", "annual_dv_km_s",
        "pol_high_dv", "delta_v_km_s", "predicted_delta_v_km_s",
        "dv_stats.mean", "dv_stats.std", "dv_stats.p95",
        "dv_stats.low_2sigma", "dv_stats.high_2sigma",
    )

    _VELOCITY_TEMPLATES = (
        "partials/pol_results.html",
        "partials/pol_mc_results.html",
        "partials/notso_results.html",
        "partials/intercept_geometry.html",
    )

    def test_the_panels_read_no_km_s_field_at_all(self) -> None:
        offenders: list[str] = []
        for rel in self._VELOCITY_TEMPLATES:
            path = _TEMPLATES / rel
            for i, line in _rendered_lines(path):
                for field in self._KM_S_FIELDS:
                    if re.search(re.escape(field) + r"(?!\w)", line):
                        offenders.append(f"{rel}:{i}: {field} -> {line.strip()[:90]}")
        assert not offenders, (
            "these panels still read a km/s field, so converting the astro "
            "result at the route boundary would double-convert them:\n  "
            + "\n  ".join(offenders)
        )

    def test_the_conversion_is_exactly_one_factor_of_a_thousand(self) -> None:
        """Pinned numerically, so a second factor cannot hide behind a name."""
        from spectre.web.format_units import to_m_s

        for km_s in (0.001, 0.011, 0.0601, 0.17, 2.5):
            assert to_m_s(km_s) == pytest.approx(km_s * 1000.0, rel=1e-12)

    def test_the_view_converts_every_figure_once_and_only_once(self) -> None:
        """Every m/s value the panel shows is exactly 1,000x its km/s source."""
        from dataclasses import dataclass
        from datetime import UTC, datetime

        from spectre.web.routes.pol import _pol_view

        @dataclass
        class _Stats:
            mean: float = 0.011
            std: float = 0.002
            p95: float = 0.034
            low_2sigma: float = 0.007
            high_2sigma: float = 0.015

        @dataclass
        class _Budget:
            total_dv_km_s: float = 0.482
            annual_dv_km_s: float = 0.048

        @dataclass
        class _Manoeuvre:
            delta_v_km_s: float = 0.060
            epoch: datetime = datetime(2026, 1, 1, tzinfo=UTC)

        @dataclass
        class _Pol:
            total_dv_km_s: float = 0.482
            dv_threshold_km_s: float = 0.0005
            pol_high_dv: float = 0.015
            dv_stats: _Stats = None
            propellant_budget: _Budget = None
            manoeuvres: list = None

        pol = _Pol(dv_stats=_Stats(), propellant_budget=_Budget(),
                   manoeuvres=[_Manoeuvre()])
        view = _pol_view(pol)

        expected = {
            "total_dv_m_s": 482.0,
            "dv_threshold_m_s": 0.5,
            "pol_high_dv_m_s": 15.0,
            "dv_mean_m_s": 11.0,
            "dv_std_m_s": 2.0,
            "dv_p95_m_s": 34.0,
            "dv_low_2sigma_m_s": 7.0,
            "dv_high_2sigma_m_s": 15.0,
            "budget_total_dv_m_s": 482.0,
            "budget_annual_dv_m_s": 48.0,
        }
        for key, want in expected.items():
            assert view[key] == pytest.approx(want), (
                f"{key} is {view[key]}, expected {want}. A value 1,000x out "
                "means the conversion ran twice; 1,000x small means it did not "
                "run at all."
            )
        assert view["manoeuvre_rows"][0]["delta_v_m_s"] == pytest.approx(60.0)

    def test_a_missing_statistic_does_not_crash_the_panel(self) -> None:
        """An object with too few manoeuvres has no stats and no budget."""
        from dataclasses import dataclass

        from spectre.web.routes.pol import _pol_view

        @dataclass
        class _Bare:
            total_dv_km_s: float = 0.0
            dv_threshold_km_s: float = 0.0005
            pol_high_dv: float | None = None
            dv_stats: None = None
            propellant_budget: None = None
            manoeuvres: tuple = ()

        view = _pol_view(_Bare())
        assert view["dv_mean_m_s"] is None
        assert view["budget_total_dv_m_s"] is None
        assert view["pol_high_dv_m_s"] is None
        assert view["manoeuvre_rows"] == []


class TestEveryConvertedFigureIsActuallySupplied:
    """Moving a conversion to the route means the route must now supply it.

    Jinja's default undefined is falsy and silent. A context key the route
    forgets to pass renders as an empty string, so a panel that used to show
    "60.1 m/s" shows " m/s" and nothing raises. That is exactly how the
    refusals panel shipped dead in 0.5.14, and moving twelve conversions out of
    a template is twelve fresh chances to make the same mistake.
    """

    #: template -> the route module that renders it
    _PANELS = {
        "partials/pol_results.html": "pol.py",
        "partials/pol_mc_results.html": "pol.py",
        "partials/notso_results.html": "pol.py",
        "partials/intercept_geometry.html": "geometry.py",
    }

    @staticmethod
    def _required_names(rel: str) -> list[str]:
        from jinja2 import meta

        from spectre.web.app import templates as app_templates

        env = Environment(
            loader=FileSystemLoader(str(_TEMPLATES)), autoescape=True,
        )
        env.filters.update(app_templates.env.filters)
        source = (_TEMPLATES / rel).read_text(encoding="utf-8")
        found = meta.find_undeclared_variables(env.parse(source))
        # Only the names this change introduced: the converted figures and the
        # row wrappers that carry them.
        return sorted(
            n for n in found if n.endswith("_m_s") or n.endswith("_rows")
        )

    @pytest.mark.parametrize(("template", "route"), sorted(_PANELS.items()))
    def test_the_route_passes_every_converted_name_the_panel_reads(
        self, template: str, route: str
    ) -> None:
        required = self._required_names(template)
        assert required, f"{template} reads no converted figure; has it regressed?"
        source = (_ROUTES / route).read_text(encoding="utf-8")
        missing = [n for n in required if f'"{n}"' not in source]
        assert not missing, (
            f"{template} reads {missing} but {route} never passes "
            "them, so the panel renders blank and nothing raises"
        )

    def test_the_hill_frame_panel_renders_its_converted_burn_state(self) -> None:
        """A small panel, rendered for real under StrictUndefined.

        The fixture is the REAL ``RelativeGeometry`` dataclass, so a field added
        to it fails here rather than rendering as an empty string in the panel.
        """
        from spectre.astro.cw_geometry import CWState, RelativeGeometry
        from spectre.web.app import templates as app_templates

        env = Environment(
            loader=FileSystemLoader(str(_TEMPLATES)),
            autoescape=True,
            undefined=StrictUndefined,
        )
        env.filters.update(app_templates.env.filters)

        # 0.0601 km/s radial, which is 60.1 m/s.
        geom = RelativeGeometry(
            method="lambert",
            red_name="SJ-17",
            blue_name="B_SAT_Alpha",
            n_rad_s=7.2921e-5,
            initial_range_km=12.0,
            tof_hours=6.0,
            dv_total_ms=61.3,
            burn_epoch=datetime(2026, 10, 13, 12, 0, tzinfo=UTC),
            cw_valid=True,
            validity_notes=[],
            coast_points=[],
            transfer_points=[],
            burn_state=CWState(0.0, 0.0, 0.0, 0.0601, -0.0122, 0.0034),
            arrival_range_km=4.2,
        )
        html = env.get_template("partials/intercept_geometry.html").render(
            geom=geom,
            chart_json="{}",
            burn_xd_m_s=60.1, burn_yd_m_s=-12.2, burn_zd_m_s=3.4,
        )
        assert "60" in html, "the converted radial rate is missing"
        assert "0.0601" not in html, "that is the km/s value reaching the screen"
        assert "60100" not in html, "that is the conversion applied twice"
