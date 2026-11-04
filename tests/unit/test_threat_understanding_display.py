"""Threat Understanding on screen, SPC-168: section 6.4 on the sweep, the intel card and Pattern of Life.

The Threat line comes first in a sentence of its own, then the Understanding
line with its statement and up to 3 cues (SPC-170). The verdict badge is
outlined, not filled, when Understanding is LOW, and still reads the legacy
verdict. The four-cell strip (Identity, Capability, Manoeuvres,
Interactions) lists each item's grade, age and basis in its tooltip, the
ledger is collapsed, and a Missing list names what is not held. One object
reads the same strip on every panel. I13: no sentence carries both a Threat
and an Understanding band, no percentage is rendered and no band word
stands bare.
"""

from __future__ import annotations

import dataclasses
import html
import logging
import re
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from spectre.domain import threat_understanding as tu
from spectre.domain.custody import Custody
from spectre.domain.threat_assessment import Band, CapabilityEvidence
from spectre.web import understanding_view
from spectre.web.routes import pol, threat
from spectre.web.routes.pol import HeldHistory
from tests.unit._i13 import i13_problems
from tests.unit.test_threat_understanding_sweep import (
    _FETCHED,
    _HELD,
    _NO_HISTORY,
    _RAISES,
    _SATNO,
    _held_history,
    _row,
    _satcat,
    _sweep_entry,
    cache,  # noqa: F401
)

_TEMPLATES = Path(__file__).resolve().parents[2] / "spectre" / "web" / "templates"
_STATIC = Path(__file__).resolve().parents[2] / "spectre" / "web" / "static"
_RECORD = {"assessed_threat": "Inspector", "threat_level": "HIGH", "status": "Operational", "source": "CSIS 2025"}


def _render(template: str, context: dict[str, Any]) -> str:
    """Through the application's own filters, under StrictUndefined."""
    from spectre.web.app import templates as app_templates

    env = Environment(loader=FileSystemLoader(str(_TEMPLATES)), autoescape=True, undefined=StrictUndefined)
    env.filters.update(app_templates.env.filters)
    env.globals.update(app_templates.env.globals)
    return env.get_template(template).render(**context)


def _text(fragment: str) -> list[str]:
    """The fragment's text, one entry per cell or sentence, tags and entities gone."""
    plain = html.unescape(re.sub(r"<[^>]+>", "\n", fragment))
    return [s.strip() for line in plain.splitlines() for s in re.split(r"(?<=\.)\s+", line) if s.strip()]


def _block(page: str, opening: str, tag: str) -> str:
    start = page.index(opening)
    depth, index = 0, start
    pattern = re.compile(rf"<(/?){tag}\b")
    for match in pattern.finditer(page, start):
        depth += -1 if match.group(1) else 1
        index = match.end()
        if depth == 0:
            break
    return page[start:page.index(">", index) + 1]


def _strip(page: str) -> str:
    return _block(page, '<div class="tu-strip"', "div")


@pytest.fixture
def held(monkeypatch: pytest.MonkeyPatch, cache: Any) -> Any:  # noqa: F811
    """One object: an intel record, a cached GCAT entry and an 18 SDS history, the clock an hour after it."""
    history = _held_history(_RAISES)
    now = history.pol.records[-1].epoch + timedelta(hours=1)
    for module in (threat, pol):
        monkeypatch.setattr(module, "get_intel", lambda _s: dict(_RECORD))
    monkeypatch.setattr(pol, "_utc_now", lambda: now)
    cache["satcat"] = _satcat([{"Satcat": _SATNO, "Bus": "Luch", "Owner": "RVSN"}], _FETCHED)
    return SimpleNamespace(history=history, now=now)


def _sweep_worst(history: Any, now: Any, mode: str = "REAL", tle: str = "", dv: float = 9.0) -> dict[str, Any]:
    """The sweep's worst case for the object. With *tle*, custody is judged by the sweep's own rule on it."""
    worst = threat._compute_worst_coa([_sweep_entry(dv=dv)], threat._red_capability(_SATNO))
    assert worst is not None
    regime = history.pol.regime if history.pol is not None else "GEO"
    custody = threat._red_custody(tle, history, now) if tle else _HELD
    red = threat._Red(_SATNO, tle, regime, history, custody,
                      threat.ConfidenceContext(data_mode=mode, custody=custody.state))
    shadowed = threat._with_understanding(worst, threat._red_understanding(red, worst, now))
    assert shadowed is not None
    return shadowed


def _sweep_page(worst: dict[str, Any]) -> str:
    from tests.unit.test_threat_sweep_template import _context

    return _render("partials/threat_sweep.html", _context(worst_coa=worst))


def _card_view(history: Any, now: Any, tle: str = "") -> dict[str, Any]:
    histories = {} if history.pol is None else {int(_SATNO): HeldHistory(int(_SATNO), now, pol=history.pol)}
    state = SimpleNamespace(elset_histories=histories, pol_reserve_resets={})
    view = threat._red_object_view(state, _SATNO, tle, "REAL", now)
    assert view is not None
    return view


def _card_page(view: dict[str, Any] | None) -> str:
    return _render("partials/pair_card.html", {"pair": {**_RECORD, "name": "RED", "orbit": "LEO", "country": "CHN",
                                                        "significance": "x", "source": "CSIS 2025"},
                                               "pair_label": "RED TRACK", "pair_tu": view})


def _pol_page(history: Any) -> str:
    view = pol._pol_view(history.pol)
    assert view["object_understanding"] is not None
    return _render("partials/pol_results.html", {"pol": history.pol, "source": "UDL", "pair": None, **view})


class TestTheStripMatchesOnEveryPanel:
    def test_one_object_reads_the_same_strip_on_the_sweep_the_intel_card_and_pattern_of_life(self, held: Any) -> None:
        sweep = _strip(_sweep_page(_sweep_worst(held.history, held.now)))
        card = _strip(_card_page(_card_view(held.history, held.now)))
        pattern = _strip(_pol_page(held.history))
        assert sweep == card == pattern
        assert "Manoeuvres: earned" in sweep and "Identity: earned" in sweep

    def test_with_no_history_held_the_sweep_and_the_card_still_agree(self, held: Any) -> None:
        sweep = _strip(_sweep_page(_sweep_worst(_NO_HISTORY, held.now)))
        assert sweep == _strip(_card_page(_card_view(_NO_HISTORY, held.now)))
        assert "Manoeuvres: not earned" in sweep

    def test_each_cell_opens_to_its_items_for_keyboard_and_screen_reader(self, held: Any) -> None:
        """Finding 8: the grade, age and basis are text in a details element, not only a tooltip."""
        strip = _strip(_card_page(_card_view(held.history, held.now)))
        cells = re.findall(r'<details class="tu-cell"[^>]*>\s*<summary[^>]*>([^<]*)</summary>\s*<div[^>]*>([^<]*)</div>',
                           strip)
        assert [name for name, _ in cells] == [
            "Identity: earned", "Capability: partial", "Manoeuvres: earned", "Interactions: not earned"]
        assert "GCAT entry: bus Luch, owner RVSN: B2, " in cells[0][1]
        assert cells[3][1].strip() == "nothing held"
        assert "<details class=\"tu-cell\" open" not in strip

    def test_each_cell_is_drawn_with_its_own_fill(self) -> None:
        cells = [{"name": n, "depth": d, "fill": f, "detail": ""} for n, d, f in (
            ("Identity", "earned", "full"), ("Capability", "partial", "half"), ("Manoeuvres", "not earned", "empty"))]
        strip = _render("partials/understanding_strip.html", {"tu": {"strip": cells}})
        backgrounds = re.findall(r"background:([^;\"]+)", strip)
        assert [b.strip() for b in backgrounds] == [
            "var(--surface-raised)", "linear-gradient(90deg, var(--surface-raised) 50%, transparent 50%)",
            "transparent"]

    def test_each_cell_lists_its_items_with_grade_age_and_basis(self, held: Any) -> None:
        cells = re.findall(r'title="([^"]*)"', _strip(_sweep_page(_sweep_worst(held.history, held.now))))
        assert cells[0] == "GCAT entry: bus Luch, owner RVSN: B2, " + cells[0].split("B2, ")[1]
        assert ", undated, lookup" in cells[0]
        assert cells[3] == "nothing held"


class TestTheSweep:
    def test_the_understanding_line_carries_up_to_three_cues_after_the_threat_line(self, held: Any) -> None:
        worst = _sweep_worst(held.history, held.now)
        view = worst["understanding"]
        section = _block(_sweep_page(worst), '<section class="threat-understanding"', "section")
        lines = _text(section)
        threat_at = next(i for i, s in enumerate(lines) if s.startswith("Threat:"))
        understanding_at = next(i for i, s in enumerate(lines) if s.startswith("Understanding "))
        raise_at = lines.index("Raise it by:")
        assert threat_at < understanding_at < raise_at
        assert 0 < len(view["cues"]) <= understanding_view.CUES_SHOWN
        assert lines[raise_at + 1:raise_at + 1 + len(view["cues"])] == [f"{c}." for c in view["cues"]]

    def test_the_cues_are_the_models_in_rank_order(self, held: Any) -> None:
        red = threat._Red(_SATNO, "", held.history.pol.regime, held.history, _HELD,
                          threat.ConfidenceContext(data_mode="REAL", custody=Custody.HELD))
        worst = threat._compute_worst_coa([_sweep_entry()], threat._red_capability(_SATNO))
        understanding = threat._red_understanding(red, worst, held.now)
        assert understanding is not None and understanding.cues
        view = threat._understanding_view(understanding)
        assert view["cues"] == [tu.cue_text(c) for c in understanding.cues if c.fed][:3]

    def test_the_badge_is_outlined_when_understanding_is_low_and_reads_the_same_verdict(self, held: Any) -> None:
        low = _sweep_worst(_NO_HISTORY, held.now, mode="SYNTHETIC")
        assert low["understanding"]["outline"] is True
        badge = re.search(r'<span class="spectre-band-badge[^"]*">[^<]*</span>', _sweep_page(low))
        level = low["threat_level"]
        assert badge is not None and badge.group(0) == (
            f'<span class="spectre-band-badge spectre-band-{level.lower()} spectre-band-outline">'
            f"&#9888; {level} THREAT</span>")

    def test_the_badge_is_outlined_when_no_understanding_was_computed(self) -> None:
        """Finding 9: the fill means Understanding above LOW, so a verdict with none computed is not filled."""
        worst = threat._compute_worst_coa([_sweep_entry()], CapabilityEvidence(intel_threat_level="CRITICAL"))
        assert worst is not None and "understanding" not in worst
        assert "spectre-band-outline" in _sweep_page(worst)

    def test_the_badge_stays_filled_above_understanding_low(self) -> None:
        worst = threat._compute_worst_coa([_sweep_entry()], CapabilityEvidence(intel_threat_level="CRITICAL"))
        shadowed = threat._with_understanding(worst, _row(4))
        assert shadowed is not None and shadowed["understanding"]["outline"] is False
        assert "spectre-band-outline" not in _sweep_page(shadowed)

    def test_the_missing_list_names_what_is_not_held(self) -> None:
        worst = threat._compute_worst_coa([_sweep_entry()], CapabilityEvidence(intel_threat_level="CRITICAL"))
        shadowed = threat._with_understanding(worst, _row(4))
        assert shadowed is not None
        assert shadowed["understanding"]["missing"] == list(tu.missing(_row(4).range))
        assert "Missing: Capability partial; Interactions not earned; no second provider&#39;s history" in (
            _sweep_page(shadowed))

    def test_the_ledger_stays_collapsed(self, held: Any) -> None:
        page = _sweep_page(_sweep_worst(held.history, held.now))
        details = re.search(r'<details class="tu-ledger"[^>]*>', page)
        assert details is not None and "open" not in details.group(0)


class TestTheIntelCard:
    def test_it_grades_the_record_and_names_its_cue(self, held: Any) -> None:
        lines = _text(_block(_card_page(_card_view(held.history, held.now)), '<div class="pair-understanding"',
                             "div"))
        assert "This record: undated, single open source [C3]: listed, does not move the Threat range." in lines
        cue = next(s for s in lines if s.startswith("Raise it by: analyst to date and source the intel record"))
        assert cue.endswith("about 4.0 h.")

    def test_a_record_that_sets_the_floor_says_so(self, held: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        dated = {**_RECORD, "assessed_at": held.now.isoformat()}
        monkeypatch.setattr(threat, "get_intel", lambda _s: dict(dated))
        view = _card_view(held.history, held.now)
        assert view["record"] == "This record: single open source [C2]: sets the Threat floor MEDIUM"
        assert view["record_cue"] == ""

    def test_with_no_record_the_card_has_no_record_line(self, held: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(threat, "get_intel", lambda _s: None)
        view = _card_view(held.history, held.now)
        assert (view["record"], view["record_cue"]) == ("", "")

    def test_it_keeps_the_analyst_judgement_and_without_a_view_is_as_before(self, held: Any) -> None:
        plain = _card_page(None)
        assert "pair-understanding" not in plain and "analyst judgement" in plain
        assert "analyst judgement" in _card_page(_card_view(held.history, held.now))

    def test_an_object_with_no_number_has_no_view(self) -> None:
        state = SimpleNamespace(elset_histories={}, pol_reserve_resets={})
        assert threat._red_object_view(state, None, "", "REAL", _FETCHED) is None


class TestPatternOfLife:
    def test_the_panel_shows_the_section_with_the_threat_line_first(self, held: Any) -> None:
        section = _block(_pol_page(held.history), '<section class="threat-understanding"', "section")
        lines = _text(section)
        assert lines[1:3] == ["Threat: not assessed on this panel.",
                              "The sweep bounds it by an intercept's access."]
        assert lines[3].startswith("Understanding ")
        assert re.search(r'<details class="tu-ledger"[^>]*>', section)
        assert "Missing: " in section

    def test_custody_and_normality_are_the_panels_own(self, held: Any) -> None:
        view = pol._pol_view(held.history.pol)
        assert view["custody"] is not None and view["custody"].state is Custody.HELD
        understanding = view["object_understanding"]
        assert "custody" not in understanding["understanding"]

    def test_a_failure_stays_in_the_log_and_leaves_the_panel_standing(
            self, held: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        def broken(*_a: Any, **_k: Any) -> None:
            raise RuntimeError("internal detail\nforged line")

        monkeypatch.setattr(understanding_view.tu, "assess", broken)
        with caplog.at_level(logging.WARNING, logger=understanding_view.logger.name):
            view = pol._pol_view(held.history.pol)
        assert view["object_understanding"] is None
        (record,) = [r for r in caplog.records if "Threat Understanding" in r.getMessage()]
        assert "\nforged line" not in record.getMessage()
        page = _render("partials/pol_results.html", {"pol": held.history.pol, "source": "UDL", "pair": None, **view})
        assert "threat-understanding" not in page and "internal detail" not in page


def _panels(held: Any) -> dict[str, str]:
    """The Threat Understanding block of each panel, for one object."""
    low = _sweep_page(_sweep_worst(_NO_HISTORY, held.now, mode="SYNTHETIC"))
    full = _sweep_page(_sweep_worst(held.history, held.now))
    return {
        "sweep, understanding low": _block(low, '<section class="threat-understanding"', "section"),
        "sweep, with history": _block(full, '<section class="threat-understanding"', "section"),
        "intel card": _block(_card_page(_card_view(held.history, held.now)), '<div class="pair-understanding"', "div"),
        "pattern of life": _block(_pol_page(held.history), '<section class="threat-understanding"', "section"),
    }


class TestI13OnEveryPanel:
    def test_no_shared_sentence_no_percentage_and_no_bare_band(self, held: Any) -> None:
        for name, block in _panels(held).items():
            read = " ".join([*_text(block), *re.findall(r'title="([^"]*)"', block)])
            assert "%" not in read and "per cent" not in read, name
            for sentence in _text(block):
                assert i13_problems(sentence) == [], (name, sentence)

    @pytest.mark.parametrize(("sentence", "problem"), [
        ("Understanding caps the ceiling at CRITICAL.", "CRITICAL not directly after Understanding"),
        ("Understanding is rated LOW.", "LOW not directly after Understanding"),
        ("Threat evidence reads MODERATE.", "MODERATE is not a Threat band"),
        ("Threat HIGH, Understanding LOW.", "both axes share the sentence"),
        ("It reads CRITICAL.", "bare CRITICAL"),
        ("Threat at 40% CRITICAL.", "a percentage"),
    ])
    def test_the_check_catches_a_band_under_the_wrong_axis(self, sentence: str, problem: str) -> None:
        assert problem in i13_problems(sentence)

    @pytest.mark.parametrize("sentence", [
        "Threat: assessed CRITICAL.", "Threat could be as low as HIGH.", "Understanding MODERATE.",
        "could raise the Threat floor to HIGH, 3 Threat steps, about 15 min.",
        "SJ-21 reads Understanding LOW: no history held.",
    ])
    def test_the_check_passes_the_sentences_the_console_writes(self, sentence: str) -> None:
        assert i13_problems(sentence) == []

    def test_band_colours_come_from_the_status_tokens(self, held: Any) -> None:
        for name, block in _panels(held).items():
            for colour in re.findall(r"(?:border-left|color):\s*([^;\"]+)", block):
                assert not colour.strip().startswith("#"), (name, colour)


class TestTheOutlineStyle:
    def test_the_outline_is_defined_on_the_status_tokens(self) -> None:
        css = (_STATIC / "spectre-theme.css").read_text(encoding="utf-8")
        rule = re.search(r"\.spectre-band-badge\.spectre-band-outline\s*\{([^}]*)\}", css)
        assert rule is not None
        assert "background: var(--surface)" in rule.group(1)
        assert "border: 1px solid currentColor" in rule.group(1)
        for band in ("critical", "high", "medium", "low", "minimal"):
            assert re.search(
                rf"\.spectre-band-outline\.spectre-band-{band}\s*\{{\s*color: var\(--spectre-status-{band}\);", css)


_QUIET = [(200, 0.0)]


class TestTheStripDoesNotDependOnWhichSetAPanelReads:
    """Findings 4 and 10: "no burns" is judged on the history's own window, so a quiet object reads one strip.

    The sweep and the card judge custody on the console's element set, Pattern
    of Life on the newest set it holds. With a quiet 50-day history whose
    detection floor (0.1 m/s) is below the intercept's cost, every panel
    counts the absence, whichever set it is looking at.
    """

    def test_a_quiet_object_reads_the_same_strip_on_every_panel(
            self, held: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        history = _held_history(_QUIET)
        now = history.pol.records[-1].epoch + timedelta(hours=1)
        monkeypatch.setattr(pol, "_utc_now", lambda: now)
        newest, day_old = history.pol.records[-1].tle, history.pol.records[-5].tle
        sweep = _strip(_sweep_page(_sweep_worst(history, now, tle=newest)))
        card = _strip(_card_page(_card_view(history, now, tle=day_old)))
        pattern_view = pol._pol_view(history.pol)
        assert pattern_view["object_understanding"] is not None
        pattern = _strip(_render("partials/pol_results.html",
                                 {"pol": history.pol, "source": "UDL", "pair": None, **pattern_view}))
        assert threat._red_custody(day_old, history, now).state is not Custody.HELD, "the card's set is stale"
        assert sweep == card == pattern
        assert "Manoeuvres: partial" in sweep

    def test_an_intercept_cheaper_than_the_detection_floor_is_the_one_exception(self, held: Any) -> None:
        """Section 5.3: a burn smaller than the floor could hide in the silence, so the sweep cannot count it."""
        history = _held_history(_QUIET)
        now = history.pol.records[-1].epoch + timedelta(hours=1)
        newest = history.pol.records[-1].tle
        assert "Manoeuvres: not earned" in _strip(_sweep_page(_sweep_worst(history, now, tle=newest, dv=0.05)))
        assert "Manoeuvres: partial" in _strip(_card_page(_card_view(history, now, tle=newest)))

    def test_the_card_judges_custody_by_the_sweeps_rule_on_the_console_set(
            self, held: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list[tu.Situation] = []
        assess = understanding_view.tu.assess

        def spy(items: Any, situation: tu.Situation, **kw: Any) -> tu.ThreatUnderstanding:
            seen.append(situation)
            return assess(items, situation, **kw)

        monkeypatch.setattr(understanding_view.tu, "assess", spy)
        newest = held.history.pol.records[-1].tle
        _card_view(held.history, held.now, tle=newest)
        assert [s.custody for s in seen] == [threat._red_custody(newest, held.history, held.now).state]
        assert seen[0].custody is Custody.HELD


class TestOnlyFedCuesAreShown:
    """Finding 1 and 3: a cue SPECTRE cannot read the result of is not offered to the operator."""

    def test_contrast_b_shows_only_the_record_cue(self) -> None:
        from tests.unit.test_threat_understanding_cues import _contrast_b

        understanding = tu.assess(*_contrast_b(), with_cues=True)
        assert [c.fed for c in understanding.cues] == [False, False, True]
        assert understanding_view.understanding_view(understanding)["cues"] == [
            "analyst to date and source the intel record: could raise the Threat floor to MEDIUM, 2 Threat steps, "
            "about 4.0 h"]

    def test_no_more_than_three_cues_are_shown_in_rank_order(self) -> None:
        from tests.unit.test_threat_understanding_cues import _contrast_b

        understanding = tu.assess(*_contrast_b(), with_cues=True)
        (record,) = [c for c in understanding.cues if c.fed]
        five = tuple(dataclasses.replace(record, observation=f"collection {n}") for n in range(5))
        view = understanding_view.understanding_view(dataclasses.replace(understanding, cues=five))
        assert [c.split(":")[0] for c in view["cues"]] == ["collection 0", "collection 1", "collection 2"]

    def test_the_sweep_names_no_conjunction_and_no_second_provider(self, held: Any) -> None:
        for history in (held.history, _held_history(_QUIET), _NO_HISTORY):
            cues = " ".join(_sweep_worst(history, held.now)["understanding"]["cues"])
            assert "conjunctions" not in cues and "second provider" not in cues


class TestAPanelWithNoIntercept:
    """Findings 5 and 15: with no intercept, nothing on the panel is worked out against a ceiling no geometry set."""

    def test_its_cues_name_what_they_firm_up_and_no_threat_band(self, held: Any) -> None:
        view = pol._pol_view(_held_history(_QUIET).pol)["object_understanding"]
        assert view is not None and view["cues"]
        for cue in view["cues"]:
            assert "Threat" not in cue and "would firm up" in cue, cue

    def test_the_card_cue_is_worded_the_same_way(self, held: Any) -> None:
        assert _card_view(held.history, held.now)["record_cue"] == (
            "analyst to date and source the intel record: would firm up Identity, about 4.0 h")

    def test_access_is_left_unbounded_and_the_panel_says_where_threat_is_assessed(self, held: Any) -> None:
        signals = tu.history_signals(held.history.pol, held.history.assessment)
        obj = understanding_view.HeldObject(_SATNO, None, None, signals, Custody.HELD)
        understanding = understanding_view.object_understanding(obj, held.now, regime="LEO", data_mode="REAL")
        assert understanding is not None and understanding.range.ceiling is Band.CRITICAL
        view = understanding_view.understanding_view(understanding, intercept=False)
        assert (view["band"], view["heading"], view["note"]) == (
            "unknown", "WHAT IS UNDERSTOOD ABOUT THIS OBJECT", "")
        assert view["threat"] == "Threat: not assessed on this panel. The sweep bounds it by an intercept's access."


class TestTheOutlinedBadgeClearsTheContrastFloor:
    """Finding 6: the outlined text is 0.7rem bold, normal-size text, so 4.5:1 governs it.

    It sits on its own opaque --surface, not on the banner's band wash: on the
    wash, CRITICAL measured 4.48:1 in the dark theme.
    """

    @pytest.mark.parametrize("band", ["critical", "high", "medium", "low", "minimal"])
    def test_every_band_clears_it_in_both_themes(self, band: str) -> None:
        from tests.unit._css import ratio
        from tests.unit.test_contrast_floors import _DARK, _STEEL

        for name, tokens, surface in (("dark", _DARK, _DARK["--spectre-color-deep-space"]),
                                      ("steel", _STEEL, _STEEL["--spectre-surface-raised"])):
            measured = ratio(tokens[f"--spectre-status-{band}"], surface)
            assert measured >= 4.5, f"{band} outline in {name}: {measured:.2f}:1"
