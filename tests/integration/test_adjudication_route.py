"""Adjudicating the sweep's Threat range and Understanding (SPC-176).

The sweep holds what it showed for the red object; the analyst records agree
or disagree with the range and with Understanding, with a reason, against
that picture. The log is held per sign-in, like every other operational
record SPECTRE keeps. An override never changes a band: a later sweep shows
the same range, verdict and ledger hash. The coverage rate appears only once
30 adjudications exist, as a count.
"""

from __future__ import annotations

import html
import logging
import re
from collections.abc import Iterator
from typing import Any

import pytest

from spectre.domain.adjudication import Adjudication, Judgement, Subject
from spectre.domain.threat_assessment import Band
from spectre.web.routes import threat
from tests.integration.conftest import login_as, session_state
from tests.integration.test_form_labels import _duplicate_ids, _unlabelled
from tests.integration.test_sweep_red_history import _sweep
from tests.integration.test_threat_sweep_routes import _post, sweep_state  # noqa: F401

_GENERIC_REFUSAL = ("Not recorded: choose agree or disagree for the Threat range and for Understanding, name what you "
                    "judge when you disagree, and give a reason of up to 500 characters.")


@pytest.fixture(autouse=True)
def _quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(threat, "start_watch", lambda *_a, **_k: None)


@pytest.fixture
def fresh(sweep_state: Any) -> Iterator[Any]:  # noqa: F811
    """The sign-in's state with no adjudication held, restored afterwards."""
    saved = (sweep_state.adjudication_subject, sweep_state.adjudications)
    sweep_state.adjudication_subject, sweep_state.adjudications = None, ()
    yield sweep_state
    sweep_state.adjudication_subject, sweep_state.adjudications = saved


def _flat(text: str) -> str:
    return " ".join(text.split())


def _hidden_hash(page: str) -> str:
    found = re.search(r'name="ledger_hash" value="([0-9a-f]{64})"', page)
    assert found is not None
    return found.group(1)


def _hidden(page: str) -> tuple[str, str]:
    """The picture the form names: its ledger hash and its object's catalogue number."""
    found = re.search(r'name="satno" value="([^"]*)"', page)
    assert found is not None
    return _hidden_hash(page), found.group(1)


def _adjudicate(client: Any, cookie: str, ledger_hash: str, satno: str = "", **fields: str) -> str:
    data = {"ledger_hash": ledger_hash, "satno": satno, "on_range": "agree", "on_understanding": "agree",
            "reason": "consistent with the imagery", **fields}
    resp = _post(client, cookie, "adjudicate", data)
    assert resp.status_code == 200
    return _flat(resp.text)


class TestTheSweepOffersIt:
    def test_the_panel_names_the_picture_and_says_how_many_more_are_needed(
            self, client: Any, auth_cookie: str, fresh: Any) -> None:
        page = _sweep(client, auth_cookie)
        assert 'id="adjudication"' in page
        subject = fresh.adjudication_subject
        assert isinstance(subject, Subject)
        assert subject.name == "RED-GEO"
        assert _hidden(page) == (subject.ledger_hash, subject.satno)
        assert re.search(rf"Ledger hash {subject.ledger_hash[:16]}", page)
        assert "No adjudications are recorded yet. A coverage rate needs 30, so 30 more are needed." in page

    def test_every_field_is_labelled_and_no_id_repeats(self, client: Any, auth_cookie: str, fresh: Any) -> None:
        page = _sweep(client, auth_cookie)
        start = page.index('<section class="adjudication"')
        panel = page[start:page.index("</section>", start)]
        assert "<form" in panel and "<textarea" in panel
        assert _unlabelled(panel) == []
        assert _duplicate_ids(page) == []

    def test_the_reason_box_stops_at_the_reason_limit(self, client: Any, auth_cookie: str, fresh: Any) -> None:
        # The browser stops typing at the limit the server enforces, so the analyst is never refused for length.
        page = _sweep(client, auth_cookie)
        found = re.search(r'<textarea id="adj-reason"[^>]*>', page)
        assert found is not None
        assert 'maxlength="500"' in found.group(0)


class TestRecording:
    def test_an_agreement_is_recorded_and_counted(self, client: Any, auth_cookie: str, fresh: Any) -> None:
        page = _sweep(client, auth_cookie)
        panel = _adjudicate(client, auth_cookie, *_hidden(page))
        (entry,) = fresh.adjudications
        assert isinstance(entry, Adjudication) and entry.held and entry.analyst == "testadmin"
        assert entry.subject is fresh.adjudication_subject
        assert "1 adjudication is recorded. A coverage rate needs 30, so 29 more are needed." in panel
        assert "RED-GEO (" in panel and ": agreed." in panel

    def test_a_disagreement_names_what_the_analyst_judges(self, client: Any, auth_cookie: str, fresh: Any) -> None:
        page = _sweep(client, auth_cookie)
        panel = _adjudicate(client, auth_cookie, *_hidden(page), on_range="disagree", analyst_threat="MINIMAL",
                            reason="a station-keeping move")
        (entry,) = fresh.adjudications
        assert (entry.on_range, entry.analyst_threat) == (Judgement.DISAGREE, Band.MINIMAL)
        assert "the analyst judges Threat MINIMAL" in panel

    def test_the_reason_is_escaped(self, client: Any, auth_cookie: str, fresh: Any) -> None:
        page = _sweep(client, auth_cookie)
        panel = _adjudicate(client, auth_cookie, *_hidden(page), reason="<script>alert(1)</script>")
        assert "<script>alert(1)</script>" not in panel
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in panel

    def test_the_record_is_logged_on_one_line_without_the_reason(
            self, client: Any, auth_cookie: str, fresh: Any, caplog: pytest.LogCaptureFixture) -> None:
        page = _sweep(client, auth_cookie)
        with caplog.at_level(logging.INFO, logger=threat.logger.name):
            _adjudicate(client, auth_cookie, *_hidden(page), reason="private\nforged line")
        (line,) = [r.getMessage() for r in caplog.records if "adjudication" in r.getMessage()]
        assert "\n" not in line and "private" not in line


class TestAnOverrideNeverChangesABand:
    def test_a_later_sweep_shows_the_same_range_verdict_and_hash(
            self, client: Any, auth_cookie: str, fresh: Any) -> None:
        before = _sweep(client, auth_cookie)
        held = fresh.adjudication_subject
        _adjudicate(client, auth_cookie, *_hidden(before), on_range="disagree", analyst_threat="MINIMAL",
                    on_understanding="disagree", analyst_understanding="HIGH")
        assert fresh.adjudication_subject is held
        after = _sweep(client, auth_cookie)
        badge = re.compile(r'<span class="spectre-band-badge[^"]*">[^<]*</span>')
        threat_line = re.compile(r'<div class="tu-threat"[^>]*>[^<]*</div>')
        assert badge.findall(after) == badge.findall(before)
        assert threat_line.findall(after) == threat_line.findall(before)
        assert _hidden_hash(after) == _hidden_hash(before)
        assert (fresh.adjudication_subject.floor, fresh.adjudication_subject.ceiling) == (held.floor, held.ceiling)


class TestRefusals:
    def test_with_no_picture_held_nothing_is_recorded(self, client: Any, auth_cookie: str, fresh: Any) -> None:
        panel = _adjudicate(client, auth_cookie, "a" * 64)
        assert "Not recorded: no Threat range is held to adjudicate. Run a sweep first." in panel
        assert fresh.adjudications == ()

    def test_a_stale_picture_is_refused(self, client: Any, auth_cookie: str, fresh: Any) -> None:
        _sweep(client, auth_cookie)
        panel = _adjudicate(client, auth_cookie, "b" * 64)
        assert ("Not recorded: this Threat range is no longer the one held. Run the sweep again and adjudicate "
                "what it shows.") in panel
        assert fresh.adjudications == ()

    def test_a_form_naming_another_object_is_refused(self, client: Any, auth_cookie: str, fresh: Any) -> None:
        ledger_hash, satno = _hidden(_sweep(client, auth_cookie))
        panel = _adjudicate(client, auth_cookie, ledger_hash, f"9{satno}")
        assert ("Not recorded: this Threat range is no longer the one held. Run the sweep again and adjudicate "
                "what it shows.") in panel
        assert fresh.adjudications == ()

    @pytest.mark.parametrize("fields", [
        {"reason": "   "}, {"reason": "x" * 501}, {"on_range": "maybe"}, {"on_range": "disagree"},
        {"on_range": "disagree", "analyst_threat": "SEVERE"}, {"on_understanding": "disagree"},
        {"on_understanding": "disagree", "analyst_understanding": "LOW"},
    ])
    def test_an_incomplete_adjudication_is_refused_in_plain_words(
            self, client: Any, auth_cookie: str, fresh: Any, fields: dict[str, str]) -> None:
        page = _sweep(client, auth_cookie)
        panel = _adjudicate(client, auth_cookie, *_hidden(page), **fields)
        assert _GENERIC_REFUSAL in panel
        assert "ValueError" not in panel and "Traceback" not in panel
        assert fresh.adjudications == ()


class TestTheCoverageRate:
    def test_the_thirtieth_adjudication_brings_the_rate_as_a_count(
            self, client: Any, auth_cookie: str, fresh: Any) -> None:
        page = _sweep(client, auth_cookie)
        subject = fresh.adjudication_subject
        others = tuple(
            Adjudication(subject=Subject(satno=str(k), name="X", floor=Band.MINIMAL, ceiling=Band.LOW,
                                         understanding=subject.understanding, ledger_hash="c" * 64,
                                         assessed_at=subject.assessed_at),
                         on_range=Judgement.DISAGREE, on_understanding=Judgement.AGREE, reason="r",
                         analyst="testadmin", recorded_at=subject.assessed_at,
                         analyst_threat=Band.HIGH if k < 4 else Band.LOW)
            for k in range(29))
        fresh.adjudications = others
        panel = _adjudicate(client, auth_cookie, *_hidden(page))
        assert "The earned Threat range held the analyst's judgement in 26 of 30 adjudications." in html.unescape(panel)
        assert "%" not in panel and "per cent" not in panel


class TestHeldPerSignIn:
    def test_another_sign_in_starts_with_none(self, client: Any, auth_cookie: str, fresh: Any) -> None:
        page = _sweep(client, auth_cookie)
        _adjudicate(client, auth_cookie, *_hidden(page))
        other = login_as(client, "testadmin", "testpass123")
        assert other != auth_cookie
        assert session_state(other).adjudications == ()
        assert len(fresh.adjudications) == 1
