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
from pathlib import Path

import pytest

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
