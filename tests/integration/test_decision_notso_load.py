"""Every row's NOTSO suggestion as the panel opens, its interval, and the NOTSO timeline (SPC-185, SPC-132).

Concept section 7.5: P and Conf are never filled in on the operator's behalf.
Owner ruling of 2026-11-05 on concept section 9, decision 16 (SPC-185): every
row's suggestion is loaded when the panel opens and follows every change, so
each row shows its suggestion, its basis and its interval with the control
that applies it at once, with no control to load it. Applying stays the
operator's tick, honoured at Evaluate: showing is not applying. Evaluate records each applied suggestion
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
    _P,
    _evaluate,
    _form,
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


class TestEveryRowLoadsAsThePanelOpens:
    def test_every_row_shows_its_suggestion_unticked_with_no_load_control(
        self, client: Any, auth_cookie: str, held: Any,  # noqa: F811
    ) -> None:
        raw = _region(client, auth_cookie, adv_id=["A1", "A2"], adv_name=["Approach", "Hold"],
                      adv_type=["manoeuvre", "manoeuvre"])
        assert _loads(raw) == []
        assert "Load from NOTSO" not in raw
        assert 'name="adv_loaded"' not in raw
        assert _text(raw).count(f"NOTSO suggestion for RX: P {_P}.") == 2
        assert re.findall(r'name="adv_prior" value="([^"]+)"', raw) == [f"A1|{_P}|", f"A2|{_P}|"]
        assert " checked" not in raw

    def test_each_row_shows_its_interval_and_the_control_to_apply_it(
        self, client: Any, auth_cookie: str, held: Any,  # noqa: F811
    ) -> None:
        page = _text(_region(client, auth_cookie))
        assert f"NOTSO suggestion for RX: P {_P}." in page
        assert f"P {_P} lies in 0.02 to 0.17, an exact Poisson interval, 95 in 100, on the 5 reported events" in page
        assert "Apply this suggestion to row 1's P at Evaluate, in place of the values typed" in page

    def test_the_panel_asks_for_every_row_as_it_opens_and_on_every_change(
        self, client: Any, auth_cookie: str,
    ) -> None:
        panel = client.get("/plan/decision/panel", cookies={"spectre_session": auth_cookie}).text
        region = re.search(r'<div class="adv-priors"[^>]*>', panel)
        assert region is not None
        assert 'hx-get="/plan/decision/prior"' in region.group(0)
        assert 'hx-trigger="load, change from:closest form"' in region.group(0)

    def test_a_ticked_row_stays_ticked_while_its_suggestion_is_the_one_shown(
        self, client: Any, auth_cookie: str, held: Any,  # noqa: F811
    ) -> None:
        raw = _region(client, auth_cookie, adv_prior=[f"A1|{_P}|"])
        assert re.search(rf'name="adv_prior" value="A1\|{_P}\|" checked', raw)

    def test_a_load_field_from_an_older_page_changes_nothing(
        self, client: Any, auth_cookie: str, held: Any,  # noqa: F811
    ) -> None:
        assert _region(client, auth_cookie, adv_loaded=["A1"]) == _region(client, auth_cookie)

    def test_showing_is_not_applying(self, client: Any, auth_cookie: str, held: Any) -> None:  # noqa: F811
        page = _text(_results(client, auth_cookie))
        assert "P=0.6 (judgement) · Share=0.6 (judgement) · Conf=0.7 (judgement)" in page
        assert "P and Conf are your own." in page

    def test_the_panel_says_the_suggestion_fills_nothing_until_ticked(
        self, client: Any, auth_cookie: str, held: Any,  # noqa: F811
    ) -> None:
        page = _text(_region(client, auth_cookie))
        assert ("Each row's NOTSO suggestion is shown as the panel opens. It fills neither P nor Conf: tick it to "
                "apply it at Evaluate.") in page
        assert i13_problems(page) == []

    def test_a_row_name_is_escaped(
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
               "0.17, with the other rows held at their P and the remainder of P taking up the difference." in page

    def test_under_minimax_it_says_minimax_reads_no_probability_and_shows_no_interval(
        self, client: Any, auth_cookie: str, held: Any,  # noqa: F811
    ) -> None:
        raw = _results(client, auth_cookie, adv_prior=[f"A1|{_P}|"])
        assert "Minimax does not use probability, so the NOTSO interval on row 1's P cannot move its pick and is not " \
               "shown." in _text(raw)
        assert "0.02 to 0.17" not in _text(raw)

    def test_with_nothing_applied_nothing_is_said(self, client: Any, auth_cookie: str, held: Any) -> None:  # noqa: F811
        assert 'class="prior-interval' not in _results(client, auth_cookie, strategy="expected_value")
