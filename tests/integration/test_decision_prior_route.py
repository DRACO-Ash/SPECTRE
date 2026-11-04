"""The Decision Engine panel offers a NOTSO prior beside each adversary row, and Evaluate records it (SPC-130).

Concept section 7.5: P and Conf are never filled in on the operator's behalf.
The panel shows, for each adversary row, the suggestion the bound red track's
NOTSO history supports and what it rests on (the notice count, the span and
the mapping), with a labelled control to apply it; or why none is offered.
Evaluate applies only a suggestion the operator ticked, and only while it is
still the one shown; the result says whose values each row holds. The NOTSO
cache is a file written here, the route's clock is fixed and UDL is not
connected, so no test reaches the network or reads the wall clock.
"""

from __future__ import annotations

import html
import json
import logging
import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from spectre.data.notso_cache import NotsoCache
from spectre.web import decision_prior
from spectre.web.routes import decision as decision_routes
from spectre.web.routes.pol import HeldHistory
from tests.integration.conftest import session_state
from tests.integration.test_decision_input_validation import _evaluate, _form
from tests.unit._i13 import i13_problems
from tests.unit.test_elset_freshness import _checksummed, _tle

_NOW = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)
_YEAR = datetime(2025, 1, 1, tzinfo=UTC)
#: Day of 2025 of each manoeuvre notice for RX (50322); the cache covers 1 Jan to 20 Jul 2025, 200 days.
_DAYS = (10, 40, 80, 120, 160)
#: 5 events over 200 days carried over 72 h, rounded down: 1 - exp(-5 x 72 / 4800) is 0.072.
_P = "0.07"


def _record(day: int, kind: str = "Maneuver", sat: str = "50322") -> dict[str, Any]:
    event = _YEAR + timedelta(days=day - 1, hours=12)
    created = event + timedelta(hours=2)
    return {
        "id": f"{kind}-{sat}-{day}", "createdAt": created.strftime("%Y-%m-%dT%H:%M:%S.000Z"), "source": "JCO",
        "msgType": "TACREP_NOTSO", "dataMode": "REAL",
        "msgBody": {"SatIds": [sat], "Event_Class": f"{kind} / {sat} / RX",
                    "Event_Description": f"Jday {day:03d} 1200z: event."},
    }


def _write_cache(
    tmp_path: Path, days: tuple[int, ...] = _DAYS, *, filled: bool = True, first_at: str = "2025-01-01T00:00:00.000Z",
) -> NotsoCache:
    """RX's notices on *days*, and, when *filled*, a notice for another object every other day, as a synced feed holds:
    a week with no notice for any object is a gap in the cache, not quiet time."""
    first = {**_record(1, "Launch", "99999"), "createdAt": first_at}
    others = [_record(d, "Other", "99999") for d in range(3, 201, 2)] if filled else []
    records = sorted([first, *others, *(_record(d) for d in days)], key=lambda r: r["createdAt"])
    path = tmp_path / "notso_cache.json"
    path.write_text(json.dumps({"metadata": {"last_sync_utc": "2025-07-20T00:00:00Z", "total_records": len(records)},
                                "records": records}), encoding="utf-8")
    return NotsoCache(path)


@pytest.fixture
def held(auth_cookie: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Any]:
    """A red track RX (50322) held, its orbit 5 h old at the route's fixed clock, and a NOTSO cache written here."""
    from spectre.domain.models import RedTrack

    state = session_state(auth_cookie)
    saved = (list(state.red_tracks), dict(state.elset_histories), state.threat_picture)
    monkeypatch.setattr(decision_routes, "_utc_now", lambda: _NOW)
    cache = _write_cache(tmp_path)
    monkeypatch.setattr(decision_prior, "get_notso_cache", lambda: cache)
    state.red_tracks = [RedTrack("RX", _tle(_NOW - timedelta(hours=5), satno=50322), data_mode="REAL")]
    state.threat_picture = None
    yield state
    state.red_tracks, state.threat_picture = saved[0], saved[2]
    state.elset_histories.clear()
    state.elset_histories.update(saved[1])


def _text(page: str) -> str:
    return html.unescape(" ".join(re.sub(r"<[^>]+>", " ", page).split()))


def _region(client: Any, cookie: str, **params: Any) -> str:
    query: dict[str, Any] = {"horizon_hours": "72", "adv_id": ["A1"], "adv_name": ["Approach"],
                             "adv_type": ["manoeuvre"], "red_sat": "RX"}
    query.update(params)
    resp = client.get("/plan/decision/prior", params=query, cookies={"spectre_session": cookie})
    assert resp.status_code == 200
    return resp.text


def _ticks(page: str) -> list[str]:
    return re.findall(r'<input type="checkbox" name="adv_prior" value="([^"]+)"', page)


def _held_history(state: Any) -> None:
    """RX's element-set history held an hour ago: 6 burns above GEO's reporting threshold, 5 beside a notice.

    An hour old, so custody, which reads only a copy under 30 min old, asks for a fresh one and is told UDL is not
    connected; the prior reads the copy held whatever its age, since its age changes nothing it measured.
    """
    burns = [*(_YEAR + timedelta(days=d - 1, hours=14) for d in _DAYS), _YEAR + timedelta(days=190)]
    after = SimpleNamespace(sma_km=42164.0)
    pol = SimpleNamespace(
        satno=50322, regime="GEO", candidate_manoeuvres=[],
        records=[SimpleNamespace(epoch=_YEAR), SimpleNamespace(epoch=_YEAR + timedelta(days=200))],
        manoeuvres=[SimpleNamespace(epoch=b, delta_v_km_s=0.005, tle_before=after, tle_after=after) for b in burns],
    )
    state.elset_histories[50322] = HeldHistory(50322, _NOW - timedelta(hours=1), pol=pol)


class TestTheRegionBesideTheRows:
    def test_with_no_red_track_bound_it_says_to_bind_one(self, client: Any, auth_cookie: str, held: Any) -> None:
        page = _text(_region(client, auth_cookie, red_sat=""))
        assert "Bind a red track to be offered a NOTSO suggestion for each row's P and Conf." in page
        assert _ticks(_region(client, auth_cookie, red_sat="")) == []

    def test_a_manoeuvre_row_is_offered_a_suggestion_with_its_basis_and_a_labelled_control(
        self, client: Any, auth_cookie: str, held: Any,
    ) -> None:
        raw = _region(client, auth_cookie)
        page = _text(raw)
        assert f"NOTSO suggestion for RX: P {_P}." in page
        assert "5 reported events (5 notices) in the 200 days the NOTSO cache covers from 01 Jan 2025 to 20 Jul 2025, " \
               "where" in page
        assert "manoeuvre and proximity operations notices count as a manoeuvre" in page
        assert "No Conf is offered: no element-set history is held for RX" in page
        assert _ticks(raw) == [f"A1|{_P}|"]
        assert re.search(r"<label[^>]*>\s*<input type=\"checkbox\" name=\"adv_prior\"[^>]*>\s*Apply this suggestion "
                         r"to row 1's P at Evaluate", raw)

    def test_a_held_history_earns_a_conf(self, client: Any, auth_cookie: str, held: Any) -> None:
        _held_history(held)
        raw = _region(client, auth_cookie)
        assert f"NOTSO suggestion for RX: P {_P}, Conf 0.30." in _text(raw)
        assert "covered, 5 of 6, is 0.43, capped at 0.30, the most SPECTRE gives a NOTSO filing" in _text(raw)
        assert _ticks(raw) == [f"A1|{_P}|0.30"]
        assert "Apply this suggestion to row 1's P and Conf at Evaluate, in place of the values typed" in _text(raw)

    def test_a_no_action_row_is_offered_nothing_and_says_why(self, client: Any, auth_cookie: str, held: Any) -> None:
        raw = _region(client, auth_cookie, adv_type=["no_action"])
        assert "A quiet NOTSO record is not evidence that RX is inactive" in _text(raw)
        assert _ticks(raw) == []

    def test_below_the_floor_nothing_is_offered(
        self, client: Any, auth_cookie: str, held: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        cache = _write_cache(tmp_path, days=(10, 40))
        monkeypatch.setattr(decision_prior, "get_notso_cache", lambda: cache)
        raw = _region(client, auth_cookie)
        assert "2 reported manoeuvre events for RX" in _text(raw)
        assert _ticks(raw) == []

    def test_spells_the_cache_holds_nothing_for_are_gaps_not_quiet_time(
        self, client: Any, auth_cookie: str, held: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        # Only RX's own notices and the first record: nothing for any object for a month at a time.
        cache = _write_cache(tmp_path, filled=False)
        monkeypatch.setattr(decision_prior, "get_notso_cache", lambda: cache)
        page = _text(_region(client, auth_cookie))
        assert "5 reported events (5 notices) in the 38 days the NOTSO cache covers from 01 Jan 2025 to 13 Jun 2025, " \
               "leaving out 5 spells with no notice for any object, which are gaps in the cache, not quiet" in page
        assert "NOTSO suggestion for RX: P 0.32." in page

    def test_time_before_the_red_objects_launch_year_is_not_counted_as_quiet(
        self, client: Any, auth_cookie: str, held: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        # RX's element set names it 25001A, launched in 2025: the cache's last days of 2024 are not RX's quiet days.
        cache = _write_cache(tmp_path, first_at="2024-12-25T00:00:00.000Z")
        monkeypatch.setattr(decision_prior, "get_notso_cache", lambda: cache)
        line1, line2 = held.red_tracks[0].tle.split("\n")
        held.red_tracks[0].tle = f"{_checksummed(line1.replace('20001A', '25001A'))}\n{line2}"
        page = _text(_region(client, auth_cookie))
        assert "in the 200 days the NOTSO cache covers from 01 Jan 2025 to 20 Jul 2025, none of them before the start " \
               "of RX's launch year, 2025, where" in page

    def test_a_tick_still_matching_stays_ticked_and_a_stale_one_does_not(
        self, client: Any, auth_cookie: str, held: Any,
    ) -> None:
        kept = _region(client, auth_cookie, adv_prior=[f"A1|{_P}|"])
        stale = _region(client, auth_cookie, adv_prior=["A1|0.50|"])
        assert f'value="A1|{_P}|" checked' in kept
        assert " checked" not in stale

    def test_every_row_is_listed_by_its_number_and_name(self, client: Any, auth_cookie: str, held: Any) -> None:
        page = _text(_region(client, auth_cookie, adv_id=["A1", "A3"], adv_name=["Approach", "Hold"],
                             adv_type=["manoeuvre", "posture_change"]))
        assert "Row 1, Approach (manoeuvre)" in page
        assert "Row 2, Hold (posture change)" in page
        assert "No NOTSO type maps to posture change, so no suggestion is offered for it." in page

    def test_a_row_name_is_escaped(self, client: Any, auth_cookie: str, held: Any) -> None:
        raw = _region(client, auth_cookie, adv_name=["<script>alert(1)</script>"])
        assert "<script>alert(1)" not in raw
        assert "&lt;script&gt;" in raw

    def test_an_unreadable_horizon_offers_nothing_and_says_so(self, client: Any, auth_cookie: str, held: Any) -> None:
        page = _text(_region(client, auth_cookie, horizon_hours="nan"))
        assert "Enter a horizon above 0 h and at most 720 h to be offered a NOTSO suggestion." in page

    @pytest.mark.parametrize("hours", ["0", "-1", "720.5"])
    def test_a_horizon_outside_what_evaluate_takes_offers_nothing(
        self, client: Any, auth_cookie: str, held: Any, hours: str,
    ) -> None:
        # A horizon of 0 would reach the prior, which refuses it; the region answers with the note, never an error.
        page = _text(_region(client, auth_cookie, horizon_hours=hours))
        assert page == "Enter a horizon above 0 h and at most 720 h to be offered a NOTSO suggestion."

    def test_the_longest_horizon_evaluate_takes_is_offered_a_suggestion(
        self, client: Any, auth_cookie: str, held: Any,
    ) -> None:
        assert _ticks(_region(client, auth_cookie, horizon_hours="720")) == ["A1|0.52|"]

    def test_no_more_rows_are_listed_than_the_panel_holds(self, client: Any, auth_cookie: str, held: Any) -> None:
        ids = [f"A{i}" for i in range(1, 8)]
        page = _text(_region(client, auth_cookie, adv_id=ids, adv_name=ids, adv_type=["manoeuvre"] * len(ids)))
        assert "Row 5, A5 (manoeuvre)" in page
        assert "Row 6" not in page

    def test_a_red_track_not_held_says_so(self, client: Any, auth_cookie: str, held: Any) -> None:
        page = _text(_region(client, auth_cookie, red_sat="GONE"))
        assert "Red track GONE" in page

    def test_no_sentence_breaks_i13(self, client: Any, auth_cookie: str, held: Any) -> None:
        _held_history(held)
        page = _text(_region(client, auth_cookie, adv_id=["A1", "A2"], adv_name=["a", "b"],
                             adv_type=["manoeuvre", "no_action"]))
        assert [s for s in re.split(r"(?<=\.)\s", page) if i13_problems(s)] == []


class TestThePanel:
    def test_the_panel_loads_the_region_beside_the_rows_and_refreshes_it_on_any_change(
        self, client: Any, auth_cookie: str, held: Any,
    ) -> None:
        resp = client.get("/plan/decision/panel", cookies={"spectre_session": auth_cookie})
        assert resp.status_code == 200
        region = re.search(r'<div class="adv-priors"[^>]*>', resp.text)
        assert region is not None
        assert 'hx-get="/plan/decision/prior"' in region.group(0)
        assert 'hx-trigger="load, change from:closest form"' in region.group(0)
        assert 'hx-include="closest form"' in region.group(0)
        assert " on" not in region.group(0).replace(" one", "")

    def test_the_region_takes_nothing_from_the_evaluate_form_around_it(
        self, client: Any, auth_cookie: str, held: Any,
    ) -> None:
        # Inside the form the region would take the form's target and swap its reply into the results, where its
        # apply controls sit outside the form and no tick reaches Evaluate; and the form's disabled element, a
        # submit button the region does not hold, which htmx cannot find and throws on, so nothing is asked for.
        resp = client.get("/plan/decision/panel", cookies={"spectre_session": auth_cookie})
        *around, (_, region) = _lineage(resp.text, "adv-priors")
        assert any(tag == "form" for tag, _ in around)
        taken = {name for _, attrs in around for name in attrs if name in _INHERITED}
        assert taken
        assert sorted(name for name in taken if name not in region) == []
        assert (region["hx-target"], region["hx-swap"]) == ("this", "innerHTML")


#: Attributes htmx 1.9.12 (static/htmx.min.js) reads from the nearest element that sets one, so an element inside
#: the evaluate form takes the form's own unless it sets its own.
_INHERITED = ("hx-target", "hx-swap", "hx-select", "hx-select-oob", "hx-indicator", "hx-disabled-elt", "hx-include",
              "hx-vals", "hx-headers", "hx-params", "hx-confirm", "hx-prompt", "hx-sync", "hx-push-url",
              "hx-replace-url", "hx-encoding")
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class _Lineage(HTMLParser):
    """The open elements, each as (tag, attributes), at the first element whose class list holds *wanted*."""

    def __init__(self, wanted: str) -> None:
        super().__init__()
        self.wanted = wanted
        self.stack: list[tuple[str, dict[str, str]]] = []
        self.found: list[tuple[str, dict[str, str]]] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        here = (tag, {k: v or "" for k, v in attrs})
        if self.found is None and self.wanted in here[1].get("class", "").split():
            self.found = [*self.stack, here]
        if tag not in _VOID:
            self.stack.append(here)

    def handle_endtag(self, tag: str) -> None:
        while self.stack and self.stack.pop()[0] != tag:
            pass


def _lineage(page: str, wanted: str) -> list[tuple[str, dict[str, str]]]:
    parser = _Lineage(wanted)
    parser.feed(page)
    assert parser.found is not None
    return parser.found


def _results(client: Any, cookie: str, **form: Any) -> str:
    resp = _evaluate(client, cookie, _form(**{"red_sat": "RX", **form}))
    assert resp.status_code == 200
    return resp.text


class TestEvaluate:
    def test_values_typed_are_the_operators_own(self, client: Any, auth_cookie: str, held: Any) -> None:
        page = _results(client, auth_cookie)
        assert "error-msg" not in page
        assert "P and Conf are your own." in _text(page)
        assert "P=0.6 · Conf=0.7" in _text(page)

    def test_a_ticked_suggestion_still_shown_is_applied_and_recorded(
        self, client: Any, auth_cookie: str, held: Any,
    ) -> None:
        page = _results(client, auth_cookie, adv_prior=[f"A1|{_P}|"])
        assert "error-msg" not in page
        text = _text(page)
        assert f"P={_P} · Conf=0.7" in text
        assert f"P {_P} is the NOTSO suggestion you applied; Conf is your own." in text

    def test_a_ticked_suggestion_with_a_conf_applies_both(self, client: Any, auth_cookie: str, held: Any) -> None:
        _held_history(held)
        page = _results(client, auth_cookie, adv_prior=[f"A1|{_P}|0.30"])
        assert f"P {_P} and Conf 0.30 are the NOTSO suggestion you applied." in _text(page)

    def test_a_suggestion_that_changed_since_it_was_shown_is_refused(
        self, client: Any, auth_cookie: str, held: Any,
    ) -> None:
        page = _results(client, auth_cookie, adv_prior=["A1|0.50|"])
        assert 'class="error-msg"' in page
        assert "The NOTSO suggestion for row 1 has changed since it was shown" in _text(page)

    def test_a_tick_on_a_row_offered_nothing_is_refused(self, client: Any, auth_cookie: str, held: Any) -> None:
        page = _results(client, auth_cookie, adv_type=["no_action"], adv_prior=[f"A1|{_P}|"])
        assert "Row 1 asks for the NOTSO suggestion, but none is offered now: No NOTSO type maps" in _text(page)

    def test_a_tick_with_no_red_track_bound_is_refused(self, client: Any, auth_cookie: str, held: Any) -> None:
        page = _results(client, auth_cookie, red_sat="", adv_prior=[f"A1|{_P}|"])
        assert "Row 1 asks for the NOTSO suggestion, but no red track is bound to suggest one for." in _text(page)

    def test_a_tick_for_a_row_since_removed_is_ignored(self, client: Any, auth_cookie: str, held: Any) -> None:
        page = _results(client, auth_cookie, adv_prior=[f"A9|{_P}|"])
        assert "error-msg" not in page
        assert "P and Conf are your own." in _text(page)

    @pytest.mark.parametrize("tick", ["A1", f"|{_P}|"])
    def test_an_unreadable_tick_is_refused(self, client: Any, auth_cookie: str, held: Any, tick: str) -> None:
        page = _results(client, auth_cookie, adv_prior=[tick])
        assert "A NOTSO suggestion ticked cannot be read; reload the panel." in _text(page)

    def test_an_applied_suggestion_is_logged_by_its_row(
        self, client: Any, auth_cookie: str, held: Any, caplog: pytest.LogCaptureFixture,
    ) -> None:
        with caplog.at_level(logging.INFO, logger="spectre.web.decision_prior"):
            _results(client, auth_cookie, adv_prior=[f"A1|{_P}|"])
        assert "decision_prior: NOTSO suggestion applied to rows A1" in caplog.text


class TestWhatTheRegionCannotWorkOut:
    def test_a_red_track_with_no_catalogue_number_is_offered_nothing(self, held: Any) -> None:
        from spectre.domain.decision import ActionType, BoundElset

        red = BoundElset(side="red", name="RX", stk_name="RX", satno=None, tle="1 x\n2 x", data_mode="REAL",
                         epoch=None, age_hours=None, limit_hours=None)
        prior = decision_prior.offered_prior(held, red, ActionType.MANOEUVRE, 72.0, _NOW)
        assert prior == decision_prior.NoPrior(
            "RX has no catalogue number to look up in the NOTSO cache, so no suggestion is offered.",
        )

    def test_an_empty_cache_offers_nothing_and_says_to_sync_it(
        self, client: Any, auth_cookie: str, held: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        empty = tmp_path / "empty.json"
        empty.write_text(json.dumps({"metadata": {"last_sync_utc": None}, "records": []}), encoding="utf-8")
        cache = NotsoCache(empty)
        monkeypatch.setattr(decision_prior, "get_notso_cache", lambda: cache)
        page = _text(_region(client, auth_cookie))
        assert "The NOTSO cache holds no records yet, so no suggestion is offered." in page

    def test_a_cache_whose_records_carry_no_creation_time_is_not_called_empty(
        self, client: Any, auth_cookie: str, held: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        undated = tmp_path / "undated.json"
        records = [{**_record(d), "createdAt": None} for d in _DAYS]
        undated.write_text(json.dumps({"metadata": {"last_sync_utc": None}, "records": records}), encoding="utf-8")
        cache = NotsoCache(undated)
        monkeypatch.setattr(decision_prior, "get_notso_cache", lambda: cache)
        page = _text(_region(client, auth_cookie))
        assert "holds no records yet" not in page
        assert "The NOTSO cache's 5 records give no creation time up to now, so the time the cache covers is unknown " \
               "and no suggestion is offered." in page

    def test_a_horizon_that_is_not_a_number_offers_nothing(self, client: Any, auth_cookie: str, held: Any) -> None:
        page = _text(_region(client, auth_cookie, horizon_hours="soon"))
        assert "Enter a horizon above 0 h and at most 720 h to be offered a NOTSO suggestion." in page

    def test_an_unknown_action_type_reads_as_a_manoeuvre_as_evaluate_reads_it(
        self, client: Any, auth_cookie: str, held: Any,
    ) -> None:
        assert "Row 1, Approach (manoeuvre)" in _text(_region(client, auth_cookie, adv_type=["bogus"]))

    def test_a_held_history_spanning_no_window_earns_no_conf(self, client: Any, auth_cookie: str, held: Any) -> None:
        pol = SimpleNamespace(satno=50322, regime="GEO", records=[], manoeuvres=[], candidate_manoeuvres=[])
        held.elset_histories[50322] = HeldHistory(50322, _NOW - timedelta(hours=1), pol=pol)
        # A history holding no element sets measured nothing: it reads as none held, not as too few burns.
        assert "No Conf is offered: no element-set history is held for RX" in _text(_region(client, auth_cookie))


class TestTheLaunchYear:
    @pytest.mark.parametrize(("tle", "year"), [
        ("1 00005U 58002B   25001.00000000  .00000000  00000-0  00000-0 0  9990\n2 00005", 1958),
        ("RX\n1 50322U 25001A   25001.00000000  .00000000  00000-0  00000-0 0  9990\n2 50322", 2025),
        ("1 50322U          25001.00000000  .00000000  00000-0  00000-0 0  9990\n2 50322", None),
    ])
    def test_it_is_read_from_the_international_designator(self, tle: str, year: int | None) -> None:
        assert decision_prior.launch_year(tle) == year
