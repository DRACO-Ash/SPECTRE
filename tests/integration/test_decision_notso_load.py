"""Load from NOTSO per adversary row, the interval beside it, and the NOTSO timeline in the results (SPC-131, SPC-132).

Concept section 7.5: P and Conf are never filled in on the operator's behalf.
The panel lists each adversary row with a labelled "Load from NOTSO" control;
nothing is worked out for a row until the operator loads it, and loading
shows the suggestion, its basis and its interval with the control that
applies it: loading is not applying. Evaluate records each applied suggestion
with the notices behind it on a timeline, dated, with the covered periods and
the gaps named in words. Under expected value the result says whether the pick
changes across each applied P's interval; under minimax it says minimax reads
no probability and shows no interval. The NOTSO cache is a file written here,
the route's clock is fixed and UDL is not connected, so no test reaches the
network or reads the wall clock.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from spectre.web import decision_prior
from tests.integration.test_decision_prior_route import (
    _INHERITED,
    _P,
    _evaluate,
    _form,
    _lineage,
    _text,
    _write_cache,
    held,  # noqa: F401  (the fixture, used by name)
)
from tests.unit._i13 import i13_problems


def _region(client: Any, cookie: str, **params: Any) -> str:
    query: dict[str, Any] = {"horizon_hours": "72", "adv_id": ["A1"], "adv_name": ["Approach"],
                             "adv_type": ["manoeuvre"], "red_sat": "RX"}
    query.update(params)
    resp = client.get("/plan/decision/prior", params=query, cookies={"spectre_session": cookie})
    assert resp.status_code == 200
    return resp.text


def _loads(page: str) -> list[str]:
    return re.findall(r'<button[^>]*class="[^"]*adv-prior-load[^"]*"[^>]*>', page)


def _results(client: Any, cookie: str, **form: Any) -> str:
    resp = _evaluate(client, cookie, _form(**{"red_sat": "RX", **form}))
    assert resp.status_code == 200
    assert "error-msg" not in resp.text
    return resp.text


class TestLoadFromNotso:
    def test_each_row_has_a_labelled_load_control_and_nothing_is_worked_out_until_it_is_pressed(
        self, client: Any, auth_cookie: str, held: Any,  # noqa: F811
    ) -> None:
        raw = _region(client, auth_cookie, adv_id=["A1", "A2"], adv_name=["Approach", "Hold"],
                      adv_type=["manoeuvre", "manoeuvre"])
        assert len(_loads(raw)) == 2
        assert 'name="adv_loaded" value="A1"' in _loads(raw)[0]
        assert 'aria-label="Load from NOTSO for row 2"' in _loads(raw)[1]
        assert ">Load from NOTSO</button>" in raw.replace("\n", "").replace("  ", "")
        assert "NOTSO suggestion for RX" not in _text(raw)
        assert 'name="adv_prior"' not in raw

    def test_loading_a_row_shows_its_suggestion_its_interval_and_the_control_to_apply_it_unticked(
        self, client: Any, auth_cookie: str, held: Any,  # noqa: F811
    ) -> None:
        raw = _region(client, auth_cookie, adv_loaded=["A1"])
        page = _text(raw)
        assert f"NOTSO suggestion for RX: P {_P}." in page
        assert f"P {_P} lies in 0.02 to 0.17, an exact Poisson interval, 95 in 100, on the 5 reported events" in page
        assert f'value="A1|{_P}|"' in raw
        assert " checked" not in raw
        assert _loads(raw) == []

    def test_a_loaded_row_stays_loaded_when_the_form_changes(
        self, client: Any, auth_cookie: str, held: Any,  # noqa: F811
    ) -> None:
        raw = _region(client, auth_cookie, adv_loaded=["A1"])
        assert re.search(r'<input type="hidden" name="adv_loaded" value="A1">', raw)

    def test_loading_one_row_leaves_the_others_unloaded(
        self, client: Any, auth_cookie: str, held: Any,  # noqa: F811
    ) -> None:
        raw = _region(client, auth_cookie, adv_id=["A1", "A2"], adv_name=["Approach", "Hold"],
                      adv_type=["manoeuvre", "manoeuvre"], adv_loaded=["A2"])
        assert len(_loads(raw)) == 1
        assert 'value="A1"' in _loads(raw)[0]
        assert re.findall(r'name="adv_prior" value="([^"]+)"', raw) == [f"A2|{_P}|"]

    def test_a_ticked_row_counts_as_loaded_without_its_hidden_field(
        self, client: Any, auth_cookie: str, held: Any,  # noqa: F811
    ) -> None:
        # Its suggestion was shown to tick it, so a change in the form keeps it shown, ticked, and keeps it loaded.
        raw = _region(client, auth_cookie, adv_prior=[f"A1|{_P}|"])
        assert _loads(raw) == []
        assert re.search(r'<input type="hidden" name="adv_loaded" value="A1">', raw)
        assert re.search(rf'name="adv_prior" value="A1\|{_P}\|" checked', raw)

    def test_loading_is_not_applying(self, client: Any, auth_cookie: str, held: Any) -> None:  # noqa: F811
        page = _text(_results(client, auth_cookie, adv_loaded=["A1"]))
        assert "P=0.6 (judgement) · Conf=0.7 (judgement)" in page
        assert "P and Conf are your own." in page

    def test_the_load_control_sets_what_it_would_otherwise_take_from_the_evaluate_form(
        self, client: Any, auth_cookie: str, held: Any,  # noqa: F811
    ) -> None:
        # Inside the form, a button htmx sends from takes the form's target, indicator and disabled element unless it
        # sets its own: its reply would land in the results, and the form's submit button, which it does not hold,
        # makes htmx throw.
        panel = client.get("/plan/decision/panel", cookies={"spectre_session": auth_cookie}).text
        form = re.search(r"<form\b[^>]*>", panel)
        region = re.search(r'<div class="adv-priors"[^>]*>', panel)
        assert form is not None
        assert region is not None
        # The region's reply swapped in where htmx puts it, inside the panel's own form and region.
        page = f"{form.group(0)}{region.group(0)}{_region(client, auth_cookie)}</div></form>"
        *around, (_, button) = _lineage(page, "adv-prior-load")
        taken = {name for _, attrs in around for name in attrs if name in _INHERITED}
        assert {"hx-target", "hx-indicator", "hx-disabled-elt"} <= taken
        assert sorted(name for name in taken if name not in button) == []
        assert (button["hx-get"], button["hx-target"], button["hx-swap"]) == (
            "/plan/decision/prior", "closest .adv-priors", "innerHTML")
        assert button["hx-include"] == "closest form"
        assert [name for name in button if name.startswith(("on", "hx-on"))] == []

    def test_the_panel_says_nothing_is_loaded_until_asked(
        self, client: Any, auth_cookie: str, held: Any,  # noqa: F811
    ) -> None:
        page = _text(_region(client, auth_cookie))
        assert "Nothing is read from NOTSO for a row until you load it; loading fills neither P nor Conf." in page

    def test_a_row_name_in_the_load_control_is_escaped(
        self, client: Any, auth_cookie: str, held: Any,  # noqa: F811
    ) -> None:
        raw = _region(client, auth_cookie, adv_id=['A1"><script>x</script>'])
        assert "<script>x" not in raw


def _section(raw: str) -> str:
    section = re.search(r'<section class="notso-timeline".*?</section>', raw, re.DOTALL)
    assert section is not None
    return section.group(0)


class TestTheTimelineInTheResults:
    def test_an_applied_suggestion_shows_the_notices_behind_it_dated_with_the_period_covered(
        self, client: Any, auth_cookie: str, held: Any,  # noqa: F811
    ) -> None:
        raw = _results(client, auth_cookie, adv_prior=[f"A1|{_P}|"])
        section = re.search(r'<section class="notso-timeline".*?</section>', raw, re.DOTALL)
        assert section is not None
        text = _text(section.group(0))
        assert "NOTSO timeline for row 1, Approach" in text
        assert "Covered: 01 Jan 2025 00:00 to 20 Jul 2025 00:00 UTC, 200.0 days" in text
        assert [n for n in ("10 Jan 2025 12:00", "09 Feb 2025 12:00", "21 Mar 2025 12:00", "30 Apr 2025 12:00",
                            "09 Jun 2025 12:00") if f"Notice: {n} UTC, manoeuvre" not in text] == []

    def test_gaps_are_named_and_drawn_apart_from_cover_without_colour(
        self, client: Any, auth_cookie: str, held: Any, monkeypatch: pytest.MonkeyPatch,  # noqa: F811
        tmp_path: Path,
    ) -> None:
        cache = _write_cache(tmp_path, filled=False)
        monkeypatch.setattr(decision_prior, "get_notso_cache", lambda: cache)
        raw = _results(client, auth_cookie, adv_prior=["A1|0.32|"])
        section = re.search(r'<section class="notso-timeline".*?</section>', raw, re.DOTALL)
        assert section is not None
        text = _text(section.group(0))
        assert text.count("Gap: ") == 5
        assert "a gap in the cache, not quiet, so it is not counted" in text
        # On the bar, a gap is hatched and outlined and a notice is a tick, each named in the legend.
        assert 'class="tl-gap"' in section.group(0)
        assert 'fill="url(#' in section.group(0)
        assert "Solid: covered. Hatched: a gap, not counted. Tick: a notice." in text
        assert re.search(r'<svg[^>]*role="img"[^>]*aria-label="[^"]+"', section.group(0))

    def test_the_time_since_the_cache_last_covered_is_named_as_not_covered(
        self, client: Any, auth_cookie: str, held: Any,  # noqa: F811
    ) -> None:
        # The cache covers to its last sync, 20 Jul 2025; the route's clock stands at 04 Nov 2026 09:00.
        text = _text(_section(_results(client, auth_cookie, adv_prior=[f"A1|{_P}|"])))
        assert ("Not covered: 20 Jul 2025 00:00 to 04 Nov 2026 09:00 UTC, 472.4 days from the cache's last covered "
                "moment to the time evaluated, with no notice for any object; not quiet, so it is not counted.") in text

    def test_the_bar_tells_its_marks_apart_by_shape_as_well_as_colour(
        self, client: Any, auth_cookie: str, held: Any,  # noqa: F811
    ) -> None:
        svg = re.search(r"<svg.*?</svg>", _section(_results(client, auth_cookie, adv_prior=[f"A1|{_P}|"])), re.DOTALL)
        assert svg is not None
        height = re.search(r'viewBox="0 0 \d+ (\d+)"', svg.group(0))
        assert height is not None
        gaps = re.findall(r"<rect class=\"tl-gap\"[^>]*>", svg.group(0))
        notices = re.findall(r"<line class=\"tl-notice\"[^>]*>", svg.group(0))
        covered = re.findall(r"<rect class=\"tl-covered\"[^>]*>", svg.group(0))
        assert gaps
        assert len(notices) == 5
        # A gap is outlined as well as hatched; a notice runs the bar's full height, taller than any band.
        assert [g for g in gaps if not re.search(r'style="[^"]*stroke:var\(--text-dim\)', g)] == []
        assert [n for n in notices if 'y1="0"' not in n or f'y2="{height.group(1)}"' not in n] == []
        assert [c for c in covered if f'height="{height.group(1)}"' in c] == []

    def test_the_bar_s_spoken_summary_counts_in_the_singular_where_there_is_one(
        self, client: Any, auth_cookie: str, held: Any,  # noqa: F811
    ) -> None:
        section = _section(_results(client, auth_cookie, adv_prior=[f"A1|{_P}|"]))
        label = re.search(r'<svg[^>]*aria-label="([^"]+)"', section)
        assert label is not None
        assert label.group(1) == "Row 1: 1 covered period, 1 gap and 5 notices; the list below dates each"

    def test_no_timeline_without_an_applied_suggestion(
        self, client: Any, auth_cookie: str, held: Any,  # noqa: F811
    ) -> None:
        assert "notso-timeline" not in _results(client, auth_cookie)

    def test_no_timeline_sentence_breaks_i13(self, client: Any, auth_cookie: str, held: Any) -> None:  # noqa: F811
        raw = _results(client, auth_cookie, adv_prior=[f"A1|{_P}|"])
        section = re.search(r'<section class="notso-timeline".*?</section>', raw, re.DOTALL)
        assert section is not None
        assert [s for s in re.split(r"(?<=\.)\s", _text(section.group(0))) if i13_problems(s)] == []


class TestTheIntervalInTheResults:
    def test_under_expected_value_the_result_says_whether_the_pick_holds_across_the_interval(
        self, client: Any, auth_cookie: str, held: Any,  # noqa: F811
    ) -> None:
        page = _text(_results(client, auth_cookie, adv_prior=[f"A1|{_P}|"], strategy="expected_value"))
        assert "Row 1, Approach: expected value recommends Hold at every P across its NOTSO interval, 0.02 to " \
               "0.17, with the other rows held at their P." in page

    def test_under_minimax_it_says_minimax_reads_no_probability_and_shows_no_interval(
        self, client: Any, auth_cookie: str, held: Any,  # noqa: F811
    ) -> None:
        raw = _results(client, auth_cookie, adv_prior=[f"A1|{_P}|"])
        assert "Minimax does not use probability, so the NOTSO interval on row 1's P cannot move its pick and is not " \
               "shown." in _text(raw)
        assert "0.02 to 0.17" not in _text(raw)

    def test_with_nothing_applied_nothing_is_said(self, client: Any, auth_cookie: str, held: Any) -> None:  # noqa: F811
        assert 'class="prior-interval' not in _results(client, auth_cookie, strategy="expected_value")
