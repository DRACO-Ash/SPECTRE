"""Unit tests for sipc.web.planning_state — per-session state isolation."""

from __future__ import annotations

from sipc.domain.models import BlueAsset, RedTrack
from sipc.web.planning_state import SessionState, clear_session_state, get_session_state


class TestSessionStateIsolation:
    def setup_method(self) -> None:
        clear_session_state("alice")
        clear_session_state("bob")

    def teardown_method(self) -> None:
        clear_session_state("alice")
        clear_session_state("bob")

    def test_separate_users_have_separate_state(self) -> None:
        alice = get_session_state("alice")
        bob = get_session_state("bob")
        alice.blue_assets.append(BlueAsset(name="Alpha", tle="line1\nline2"))
        assert len(bob.blue_assets) == 0

    def test_same_user_returns_same_object(self) -> None:
        s1 = get_session_state("alice")
        s2 = get_session_state("alice")
        assert s1 is s2

    def test_clear_removes_state(self) -> None:
        s1 = get_session_state("alice")
        s1.blue_assets.append(BlueAsset(name="Alpha", tle="l1\nl2"))
        clear_session_state("alice")
        s2 = get_session_state("alice")
        assert s2 is not s1
        assert len(s2.blue_assets) == 0

    def test_clear_nonexistent_is_noop(self) -> None:
        clear_session_state("nobody")  # should not raise


class TestSessionStateLog:
    def setup_method(self) -> None:
        clear_session_state("tester")

    def teardown_method(self) -> None:
        clear_session_state("tester")

    def test_append_log_stores_entry(self) -> None:
        state = get_session_state("tester")
        state.append_log("RUN started")
        assert "RUN started" in state.log_entries

    def test_log_evicts_oldest_when_full(self) -> None:
        from sipc.web.planning_state import _MAX_LOG_ENTRIES

        state = get_session_state("tester")
        for i in range(_MAX_LOG_ENTRIES + 5):
            state.append_log(f"entry-{i}")
        assert len(state.log_entries) == _MAX_LOG_ENTRIES
        # The oldest entries should be gone; newest should be present
        assert f"entry-{_MAX_LOG_ENTRIES + 4}" in state.log_entries
        assert "entry-0" not in state.log_entries
