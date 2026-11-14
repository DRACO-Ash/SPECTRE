"""The sweep's adjudication panel: what it holds, what a form records, and what it shows (SPC-176)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from spectre.domain.adjudication import Judgement, Subject
from spectre.domain.threat_assessment import Band
from spectre.web import adjudication_log as log
from spectre.web.routes import threat
from tests.unit.test_threat_understanding_sweep import _NOW, _row


def _state() -> Any:
    return SimpleNamespace(adjudication_subject=None, adjudications=())


def _form(ledger_hash: str, **kw: str) -> log.AdjudicationForm:
    args = {"ledger_hash": ledger_hash, "satno": "40892", "on_range": "agree", "analyst_threat": "", "on_understanding": "agree",
            "analyst_understanding": "", "reason": "seen on the imagery"}
    args.update(kw)
    return log.AdjudicationForm(**args)


class TestTheHeldPicture:
    def test_it_is_the_range_understanding_and_hash_the_page_shows(self) -> None:
        state, understanding = _state(), _row(4)
        log.hold_subject(state, "RED-GEO", "40892", understanding, _NOW)
        subject = state.adjudication_subject
        assert isinstance(subject, Subject)
        assert (subject.floor, subject.ceiling, subject.understanding) == (
            understanding.range.floor, understanding.range.ceiling, understanding.understanding.level)
        assert subject.ledger_hash == threat._understanding_view(understanding)["ledger_hash"]
        assert (subject.name, subject.satno, subject.assessed_at) == ("RED-GEO", "40892", _NOW)

    def test_a_sweep_with_no_understanding_or_no_number_holds_none(self) -> None:
        state = _state()
        log.hold_subject(state, "RED-GEO", "40892", _row(4), _NOW)
        log.hold_subject(state, "RED-GEO", "40892", None, _NOW)
        assert state.adjudication_subject is None
        log.hold_subject(state, "RED-GEO", None, _row(4), _NOW)
        assert state.adjudication_subject is None


class TestTheForm:
    def test_a_choice_left_under_agree_is_ignored(self) -> None:
        state = _state()
        log.hold_subject(state, "RED-GEO", "40892", _row(4), _NOW)
        held = state.adjudication_subject
        entry, message = log.take(state, _form(held.ledger_hash, analyst_threat="LOW", analyst_understanding="HIGH"),
                                  "analyst1", _NOW)
        assert message == log.RECORDED
        assert entry is not None and (entry.analyst_threat, entry.analyst_understanding) == (None, None)
        assert state.adjudications == (entry,)

    def test_a_disagreement_takes_the_named_band(self) -> None:
        state = _state()
        log.hold_subject(state, "RED-GEO", "40892", _row(4), _NOW)
        entry, _ = log.take(state, _form(state.adjudication_subject.ledger_hash, on_range="disagree",
                                         analyst_threat="LOW"), "analyst1", _NOW)
        assert entry is not None and (entry.on_range, entry.analyst_threat) == (Judgement.DISAGREE, Band.LOW)

    def test_a_form_from_another_object_on_the_same_ledger_is_stale(self) -> None:
        # Two objects with no held evidence rest on the same empty ledger, so the hash alone cannot tell them apart.
        state = _state()
        log.hold_subject(state, "OBJ-A", "99901", _row(4), _NOW)
        shown = state.adjudication_subject.ledger_hash
        log.hold_subject(state, "OBJ-B", "99902", _row(4), _NOW)
        assert state.adjudication_subject.ledger_hash == shown
        entry, message = log.take(state, _form(shown, satno="99901", on_range="disagree", analyst_threat="MINIMAL",
                                               reason="A is a known station-keeper"), "analyst1", _NOW)
        assert (entry, message, state.adjudications) == (None, log.STALE, ())

    def test_the_panel_names_the_object_it_holds(self) -> None:
        state = _state()
        log.hold_subject(state, "OBJ-B", "99902", _row(4), _NOW)
        assert log.view(state)["satno"] == "99902"
        assert log.view(_state())["satno"] == ""

    def test_an_unknown_level_is_incomplete(self) -> None:
        state = _state()
        log.hold_subject(state, "RED-GEO", "40892", _row(4), _NOW)
        entry, message = log.take(state, _form(state.adjudication_subject.ledger_hash, on_understanding="disagree",
                                               analyst_understanding="TOTAL"), "analyst1", _NOW)
        assert (entry, message, state.adjudications) == (None, log.INCOMPLETE, ())


class TestThePanel:
    def test_the_sweep_shows_it_only_with_a_picture_held(self) -> None:
        state = _state()
        assert log.sweep_panel(state) is None
        log.hold_subject(state, "RED-GEO", "40892", _row(4), _NOW)
        panel = log.sweep_panel(state)
        assert panel is not None and panel["subject"] is True

    def test_with_nothing_held_it_offers_no_form(self) -> None:
        view = log.view(_state(), log.NO_SUBJECT)
        assert (view["subject"], view["levels"], view["recent"], view["message"]) == (False, [], [], log.NO_SUBJECT)

    def test_it_offers_only_the_levels_that_differ_and_the_newest_entries_first(self) -> None:
        state = _state()
        log.hold_subject(state, "RED-GEO", "40892", _row(4), _NOW)
        shown = state.adjudication_subject.understanding.name
        for reason in ("one", "two", "three", "four"):
            log.hold_subject(state, "RED-GEO", "40892", _row(4), _NOW)
            state.adjudication_subject = Subject(**{**vars(state.adjudication_subject), "satno": reason})
            log.take(state, _form(state.adjudication_subject.ledger_hash, satno=reason, reason=reason), "analyst1",
                     _NOW)
        view = log.view(state)
        assert shown not in view["levels"] and len(view["levels"]) == 2
        assert [line.rsplit("Reason: ", 1)[1] for line in view["recent"]] == ["four.", "three.", "two."]
