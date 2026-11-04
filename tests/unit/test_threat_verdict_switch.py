"""The verdict switch behind a setting (SPC-175, concept section 4.8).

With the switch on, the verdict shown is the Threat ceiling when Understanding
is LOW or the Threat range spans 4 or more bands, and otherwise the current
rule's reading clamped into the range. The switch is a deployment setting,
SPECTRE_THREAT_VERDICT_SWITCH, off by default and set by no shipped
configuration: the owner signs off the reference table first (concept
section 9, decisions 2 and 3). With it off, nothing the sweep or the screen
shows changes.
"""

from __future__ import annotations

import html
import re
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from spectre.config.settings import Settings
from spectre.domain import threat_understanding as tu
from spectre.domain.custody import Custody
from spectre.domain.threat_assessment import (
    WIDE_RANGE_BANDS,
    AccessEvidence,
    ActorRange,
    ActorVerdict,
    Band,
    CapabilityEvidence,
    VerdictReading,
    assess_threat,
    rank_actors,
    read_verdict,
)
from spectre.web.routes import threat
from tests.unit._i13 import i13_problems
from tests.unit.test_threat_understanding_sweep import _HELD, _NO_HISTORY, _NOW, _RED, _sweep_entry

_ROOT = Path(__file__).resolve().parents[2]
_ENV = "SPECTRE_THREAT_VERDICT_SWITCH"


class TestTheSetting:
    def test_it_is_off_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(_ENV, raising=False)
        assert Settings().threat_verdict_switch is False

    @pytest.mark.parametrize("value", ["true", "1", "yes", "on", " TRUE "])
    def test_an_explicit_yes_turns_it_on(self, monkeypatch: pytest.MonkeyPatch, value: str) -> None:
        monkeypatch.setenv(_ENV, value)
        assert Settings().threat_verdict_switch is True

    @pytest.mark.parametrize("value", ["", "false", "0", "off", "enabled", "maybe"])
    def test_anything_else_leaves_it_off(self, monkeypatch: pytest.MonkeyPatch, value: str) -> None:
        monkeypatch.setenv(_ENV, value)
        assert Settings().threat_verdict_switch is False


#: The configuration files that build, run or describe a deployment, beside the application's own.
_CONFIGURATION = ("Dockerfile", "Dockerfile.docker-only", ".env.example", "pyproject.toml", "sonar-project.properties")


def _repository_only(name: str) -> Path:
    """A file the repository holds and the submission package may not: the test skips where it is absent."""
    path = _ROOT / name
    if not path.exists():
        pytest.skip(f"{name} is not in this checkout")
    return path


def _shipped() -> list[Path]:
    """Every configuration file that ships or runs the app: images, CI, the example environment, packaging."""
    workflows = _repository_only(".github")
    files = [_ROOT / name for name in _CONFIGURATION]
    files += sorted(workflows.rglob("*.yml"))
    files += sorted(p for p in (_ROOT / "spectre").rglob("*") if p.suffix in {".yaml", ".yml", ".json", ".toml"})
    return [p for p in files if p.is_file()]


def _setting_lines(paths: list[Path]) -> list[str]:
    """Each line in *paths* that names the switch outside a comment."""
    return [f"{path.name}:{number}" for path in paths
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
            if _ENV in line and not line.lstrip().startswith("#")]


class TestNoShippedConfigurationTurnsItOn:
    """The owner signs off first, so no file the app ships or runs under may set the switch."""

    def test_the_files_checked_include_the_images_ci_and_the_example_environment(self) -> None:
        names = {p.name for p in _shipped()}
        assert {"Dockerfile", ".env.example", "pyproject.toml", "ci.yml"} <= names

    def test_no_shipped_file_sets_it_outside_a_comment(self) -> None:
        assert _setting_lines(_shipped()) == []

    def test_the_check_sees_a_line_that_sets_it(self, tmp_path: Path) -> None:
        planted = tmp_path / "Dockerfile"
        planted.write_text(f"# {_ENV}=true is commented\nENV {_ENV}=true\n", encoding="utf-8")
        assert _setting_lines([planted]) == ["Dockerfile:2"]

    def test_the_example_environment_documents_it_commented_out(self) -> None:
        example = _repository_only(".env.example")
        assert re.search(rf"^# {_ENV}=$", example.read_text(encoding="utf-8"), re.MULTILINE)


# ── The rule (concept section 4.8), in threat_assessment ──

_LEVELS = ("LOW", "MODERATE", "HIGH")


def _bands() -> list[tuple[Band, Band, Band, Band]]:
    """Every (current reading, floor, ceiling, access) with floor <= ceiling <= access."""
    return [(old, floor, ceiling, access) for access in Band for ceiling in Band for floor in Band for old in Band
            if floor <= ceiling <= access]


class TestTheRule:
    @pytest.mark.parametrize("level", _LEVELS)
    @pytest.mark.parametrize(("old", "floor", "ceiling", "access"), _bands())
    def test_it_is_the_one_rule_threat_understanding_reads(
            self, old: Band, floor: Band, ceiling: Band, access: Band, level: str) -> None:
        reading = read_verdict(old, access, (floor, ceiling), level)
        verdict = tu.verdict_for(old, floor, ceiling, tu.Understanding[level])
        assert (reading.new, reading.assessed, reading.at_ceiling) == (verdict.band, verdict.assessed,
                                                                      verdict.at_ceiling)
        assert floor <= reading.new <= ceiling
        assert reading.old is old

    def test_understanding_low_reads_the_ceiling(self) -> None:
        reading = read_verdict(Band.MINIMAL, Band.CRITICAL, (Band.HIGH, Band.CRITICAL), "LOW")
        assert (reading.new, reading.at_ceiling) == (Band.CRITICAL, True)

    def test_a_range_of_four_bands_reads_the_ceiling_and_three_does_not(self) -> None:
        assert WIDE_RANGE_BANDS == 4
        wide = read_verdict(Band.LOW, Band.CRITICAL, (Band.LOW, Band.CRITICAL), "HIGH")
        narrow = read_verdict(Band.LOW, Band.CRITICAL, (Band.MEDIUM, Band.CRITICAL), "HIGH")
        assert (wide.new, wide.at_ceiling) == (Band.CRITICAL, True)
        assert (narrow.new, narrow.at_ceiling) == (Band.MEDIUM, False)

    def test_otherwise_the_current_reading_clamped_into_the_range(self) -> None:
        inside = read_verdict(Band.HIGH, Band.CRITICAL, (Band.MEDIUM, Band.CRITICAL), "MODERATE")
        below = read_verdict(Band.HIGH, Band.CRITICAL, (Band.MINIMAL, Band.MEDIUM), "HIGH")
        assert (inside.new, below.new) == (Band.HIGH, Band.MEDIUM)

    @pytest.mark.parametrize(("span", "access", "level", "message"), [
        ((Band.HIGH, Band.MEDIUM), Band.CRITICAL, "LOW", "floor above its ceiling"),
        ((Band.LOW, Band.CRITICAL), Band.HIGH, "LOW", "ceiling above access"),
        ((Band.LOW, Band.HIGH), Band.HIGH, "SOME", "Understanding must be one of"),
    ])
    def test_an_impossible_reading_is_refused(
            self, span: tuple[Band, Band], access: Band, level: str, message: str) -> None:
        with pytest.raises(ValueError, match=message):
            read_verdict(Band.LOW, access, span, level)

    def test_shown_is_the_current_reading_while_the_switch_is_off(self) -> None:
        reading = read_verdict(Band.HIGH, Band.CRITICAL, (Band.MINIMAL, Band.CRITICAL), "LOW")
        assert (reading.shown(switch_on=False), reading.shown(switch_on=True)) == (Band.HIGH, Band.CRITICAL)


class TestTheReasonInOnePlainLine:
    @pytest.mark.parametrize(("args", "reason"), [
        ((Band.HIGH, Band.CRITICAL, (Band.MINIMAL, Band.CRITICAL), "LOW"),
         "Understanding LOW. Threat reads its ceiling, set by access at CRITICAL. The current rule reads Threat HIGH."),
        ((Band.HIGH, Band.CRITICAL, (Band.MINIMAL, Band.MEDIUM), "LOW"),
         "Understanding LOW. Threat reads its ceiling, set by the evidence at MEDIUM, below access at CRITICAL. "
         "The current rule reads Threat HIGH."),
        ((Band.MEDIUM, Band.HIGH, (Band.MINIMAL, Band.HIGH), "MODERATE"),
         "Understanding MODERATE. Threat range MINIMAL to HIGH spans 4 bands, too wide to call a point, so Threat "
         "reads its ceiling, set by access at HIGH. The current rule reads Threat MEDIUM."),
        ((Band.HIGH, Band.CRITICAL, (Band.MEDIUM, Band.CRITICAL), "HIGH"),
         "Understanding HIGH. Threat range MEDIUM to CRITICAL holds the current rule's reading, so Threat stays "
         "HIGH. The current rule reads Threat HIGH."),
        ((Band.LOW, Band.CRITICAL, (Band.HIGH, Band.CRITICAL), "MODERATE"),
         "Understanding MODERATE. Threat range HIGH to CRITICAL sits above the current rule's reading, so Threat "
         "rises to its floor, HIGH. The current rule reads Threat LOW."),
        ((Band.CRITICAL, Band.CRITICAL, (Band.MEDIUM, Band.MEDIUM), "HIGH"),
         "Understanding HIGH. Threat range MEDIUM sits below the current rule's reading, so Threat falls to its "
         "ceiling, MEDIUM. The current rule reads Threat CRITICAL."),
    ])
    def test_each_case_says_why(self, args: tuple[Band, Band, tuple[Band, Band], str], reason: str) -> None:
        assert read_verdict(*args).reason == reason

    @pytest.mark.parametrize("level", _LEVELS)
    @pytest.mark.parametrize(("old", "floor", "ceiling", "access"), _bands())
    def test_every_reason_keeps_threat_and_understanding_apart(
            self, old: Band, floor: Band, ceiling: Band, access: Band, level: str) -> None:
        reason = read_verdict(old, access, (floor, ceiling), level).reason
        assert "\n" not in reason
        for sentence in re.split(r"(?<=\.)\s+", reason):
            assert i13_problems(sentence) == [], sentence


# ── The screen: an actor's verdict is the switched one only when it is switched ──

def _actor(verdict: Band, *, switched: VerdictReading | None = None, hours: float = 5.0,
           dv: float = 9.0) -> ActorVerdict:
    """An actor assessed *verdict*; 9 m/s in GEO gives access CRITICAL, 30 m/s access HIGH."""
    access = AccessEvidence(best_delta_v_m_s=dv, time_to_arrival_hours=hours, method="lambert", regime="GEO")
    assessment = assess_threat(access, CapabilityEvidence(intel_threat_level=verdict.label))
    return ActorVerdict(actor_name=f"A-{verdict.label}-{hours}", actor_satno=f"{int(verdict)}{int(hours)}",
                        assessment=assessment, warning_hours=hours, delta_v_m_s=dv, switched=switched)


class TestTheScreenReadsTheSwitchedVerdict:
    def test_unswitched_it_is_the_assessment(self) -> None:
        actor = _actor(Band.MEDIUM)
        assert (actor.verdict, actor.verdict_label) == (Band.MEDIUM, "MEDIUM")

    def test_switched_it_is_the_new_verdict_and_ranks_by_it(self) -> None:
        reading = read_verdict(Band.LOW, Band.CRITICAL, (Band.MINIMAL, Band.CRITICAL), "LOW")
        raised = _actor(Band.LOW, switched=reading, hours=9.0)
        other = _actor(Band.HIGH, hours=1.0)
        assert (raised.verdict, raised.verdict_label) == (Band.CRITICAL, "CRITICAL")
        assert rank_actors([other, raised]).ranked[0] is raised
        assert raised.assessment.verdict is Band.LOW


# ── The sweep: the worst case is switched only with the setting on ──

def _bundled(satno: str = "40892") -> tuple[dict[str, Any], tu.ThreatUnderstanding]:
    """A bundled red object's worst case and Threat Understanding, as the pinned legacy test builds them."""
    obj = _RED[satno]
    context = threat.ConfidenceContext(data_mode=obj["tleDataMode"], custody=Custody.HELD)
    worst = threat._compute_worst_coa([_sweep_entry()], threat._red_capability(satno), 500.0, context)
    assert worst is not None
    red = threat._Red(satno, f"{obj['line1']}\n{obj['line2']}", obj["orbitRegime"], _NO_HISTORY, _HELD, context)
    understanding = threat._red_understanding(red, worst, _NOW)
    assert understanding is not None
    return worst, understanding


class TestTheSweepSwitch:
    def test_off_the_worst_case_is_left_exactly_as_it_was(self) -> None:
        worst, understanding = _bundled()
        before = dict(worst)
        assert threat._with_verdict_switch(worst, understanding, switch_on=False) == before

    def test_on_it_reads_the_new_verdict_its_colours_the_old_one_and_the_reason(self) -> None:
        worst, understanding = _bundled()
        assert worst["threat_level"] == "HIGH"
        switched = threat._with_verdict_switch(dict(worst), understanding, switch_on=True)
        assert switched is not None
        assert (switched["threat_level"], switched["legacy_threat_level"]) == ("CRITICAL", "HIGH")
        assert (switched["threat_color"], switched["threat_bg"]) == threat._BAND_COLOURS["CRITICAL"]
        assert switched["verdict_reason"] == (
            "Understanding LOW. Threat reads its ceiling, set by access at CRITICAL. The current rule reads Threat HIGH.")
        untouched = {k: v for k, v in switched.items()
                     if k not in {"threat_level", "threat_color", "threat_bg", "legacy_threat_level", "verdict_reason"}}
        assert untouched == {k: v for k, v in worst.items() if k not in {"threat_level", "threat_color", "threat_bg"}}

    def test_with_no_worst_case_or_no_understanding_nothing_is_switched(self) -> None:
        worst, understanding = _bundled()
        assert threat._with_verdict_switch(None, understanding, switch_on=True) is None
        assert threat._with_verdict_switch(dict(worst), None, switch_on=True) == worst

    def test_the_route_reads_the_setting(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(_ENV, raising=False)
        assert threat._verdict_switch_on() is False
        monkeypatch.setenv(_ENV, "true")
        assert threat._verdict_switch_on() is True


class TestTheSweepPage:
    def _page(self, worst: dict[str, Any]) -> str:
        from tests.unit.test_threat_sweep_template import _context, _render

        return _render(_context(worst_coa=worst))

    def test_switched_the_badge_reads_the_new_verdict_and_the_reason_follows_it(self) -> None:
        worst, understanding = _bundled()
        shown = threat._with_understanding(dict(worst), understanding)
        page = self._page(threat._with_verdict_switch(shown, understanding, switch_on=True) or {})
        assert "&#9888; CRITICAL THREAT</span>" in page
        found = re.search(r'<div class="verdict-switch"[^>]*>([^<]*)</div>', page)
        assert found is not None
        reason = html.unescape(found.group(1)).strip()
        assert reason.endswith("The current rule reads Threat HIGH.")
        for sentence in re.split(r"(?<=\.)\s+", reason):
            assert i13_problems(sentence) == [], sentence

    def test_unswitched_there_is_no_reason_line(self) -> None:
        worst, understanding = _bundled()
        page = self._page(threat._with_understanding(dict(worst), understanding) or {})
        assert "&#9888; HIGH THREAT</span>" in page
        assert 'class="verdict-switch"' not in page


# ── The screen: each actor is switched only with the setting on ──

class TestTheScreenSwitch:
    def _span(self) -> ActorRange:
        return ActorRange(floor=Band.MINIMAL, ceiling=Band.CRITICAL, understanding="LOW", history_held=False,
                          at_ceiling=True)

    def test_off_the_actor_is_left_as_it_was(self) -> None:
        actor = replace(_actor(Band.LOW), understanding=self._span())
        assert threat._switched_actor(actor, switch_on=False) is actor

    def test_on_it_carries_the_reading_against_its_own_access(self) -> None:
        # Access HIGH, below CRITICAL, so a reading taken against any other access would say so.
        span = ActorRange(floor=Band.MINIMAL, ceiling=Band.HIGH, understanding="LOW", history_held=False,
                          at_ceiling=True)
        actor = replace(_actor(Band.LOW, hours=48.0, dv=30.0), understanding=span)
        assert actor.assessment.access is Band.HIGH
        switched = threat._switched_actor(actor, switch_on=True)
        assert switched.switched == read_verdict(Band.LOW, Band.HIGH, (Band.MINIMAL, Band.HIGH), "LOW")
        assert switched.switched.reason == (
            "Understanding LOW. Threat reads its ceiling, set by access at HIGH. The current rule reads Threat LOW.")
        assert switched.verdict_label == "HIGH"

    @pytest.mark.parametrize(("value", "label"), [("", "LOW"), ("true", "CRITICAL")])
    def test_the_screening_pass_reads_the_setting(
            self, monkeypatch: pytest.MonkeyPatch, value: str, label: str) -> None:
        actor = _actor(Band.LOW)
        monkeypatch.setenv(_ENV, value)
        monkeypatch.setattr(threat, "_screen_one_actor", lambda *_a: (actor, []))
        monkeypatch.setattr(threat, "_resolve_hrr_tle", lambda *_a: "tle")
        monkeypatch.setattr(threat, "_actor_range", lambda *_a: self._span())
        candidate = SimpleNamespace(actor_name="RED", actor_satno="1", regime="GEO")
        run = threat._screen_all_actors(SimpleNamespace(), [candidate], "", None, _NOW, 500.0)  # type: ignore[arg-type, list-item]
        (screened,) = run.verdicts
        assert screened.verdict_label == label

    def test_with_no_range_read_it_is_not_switched(self) -> None:
        actor = _actor(Band.LOW)
        assert threat._switched_actor(actor, switch_on=True) is actor

    def _page(self, actor: ActorVerdict) -> str:
        from tests.unit.test_threat_screen_template import _context, _render

        return _render(_context(screening=rank_actors([actor])))

    def _switched(self) -> ActorVerdict:
        actor = threat._switched_actor(replace(_actor(Band.LOW), understanding=self._span()), switch_on=True)
        assert actor.switched is not None
        return actor

    def test_the_verdict_cell_opens_on_the_reason_without_a_hover(self) -> None:
        # A keyboard or touch user never sees a title; a details element they can open, they do.
        actor = self._switched()
        found = re.search(r'<td class="screen-verdict">(.*?)</td>', self._page(actor), re.S)
        assert found is not None
        cell = found.group(1)
        assert "title=" not in cell
        summary = re.search(r"<summary>(.*?)</summary>", cell, re.S)
        reason = re.search(r"</summary>\s*<div>([^<]*)</div>", cell)
        assert summary is not None and "CRITICAL" in summary.group(1)
        assert reason is not None and html.unescape(reason.group(1)).strip() == actor.switched.reason  # type: ignore[union-attr]

    def test_the_most_dangerous_actor_says_why_its_badge_reads_its_band(self) -> None:
        actor = self._switched()
        page = self._page(actor)
        headline = page[page.index("MOST DANGEROUS ACTOR"):page.index("GEOMETRIC ACCESS")]
        found = re.search(r'<div class="verdict-switch">([^<]*)</div>', headline)
        assert found is not None
        reason = html.unescape(found.group(1)).strip()
        assert reason == actor.switched.reason  # type: ignore[union-attr]
        for sentence in re.split(r"(?<=\.)\s+", reason):
            assert i13_problems(sentence) == [], sentence

    def test_unswitched_the_headline_has_no_reason_line(self) -> None:
        page = self._page(replace(_actor(Band.LOW), understanding=self._span()))
        assert 'class="verdict-switch"' not in page

    def test_unswitched_the_cell_is_the_one_it_always_was(self) -> None:
        page = self._page(replace(_actor(Band.LOW), understanding=self._span()))
        assert 'class="screen-verdict"' not in page
        assert re.search(r'<td><span style="color:[^"]*; font-weight:700">LOW</span></td>', page)
