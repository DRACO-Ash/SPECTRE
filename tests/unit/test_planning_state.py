"""Unit tests for spectre.web.planning_state — per-session state isolation."""

from __future__ import annotations

from spectre.domain.models import BlueAsset
from spectre.web.models import SessionKey
from spectre.web.planning_state import clear_session_state, get_session_state

_ALICE, _BOB = SessionKey(1, "alice-sign-in"), SessionKey(2, "bob-sign-in")
_NOBODY, _TESTER = SessionKey(3, "never-signed-in"), SessionKey(4, "tester-sign-in")


class TestSessionStateIsolation:
    def setup_method(self) -> None:
        clear_session_state(_ALICE)
        clear_session_state(_BOB)

    def teardown_method(self) -> None:
        clear_session_state(_ALICE)
        clear_session_state(_BOB)

    def test_separate_users_have_separate_state(self) -> None:
        alice = get_session_state(_ALICE)
        bob = get_session_state(_BOB)
        alice.blue_assets.append(BlueAsset(name="Alpha", tle="line1\nline2"))
        assert len(bob.blue_assets) == 0

    def test_same_user_returns_same_object(self) -> None:
        s1 = get_session_state(_ALICE)
        s2 = get_session_state(_ALICE)
        assert s1 is s2

    def test_clear_removes_state(self) -> None:
        s1 = get_session_state(_ALICE)
        s1.blue_assets.append(BlueAsset(name="Alpha", tle="l1\nl2"))
        clear_session_state(_ALICE)
        s2 = get_session_state(_ALICE)
        assert s2 is not s1
        assert len(s2.blue_assets) == 0

    def test_clear_nonexistent_is_noop(self) -> None:
        get_session_state(_ALICE).blue_assets.append(BlueAsset(name="Alpha", tle="l1\nl2"))
        clear_session_state(_NOBODY)
        assert len(get_session_state(_ALICE).blue_assets) == 1, "another user's state was touched"


class TestSessionStateLog:
    def setup_method(self) -> None:
        clear_session_state(_TESTER)

    def teardown_method(self) -> None:
        clear_session_state(_TESTER)

    def test_append_log_stores_entry(self) -> None:
        state = get_session_state(_TESTER)
        state.append_log("RUN started")
        assert "RUN started" in state.log_entries

    def test_log_evicts_oldest_when_full(self) -> None:
        from spectre.web.planning_state import _MAX_LOG_ENTRIES

        state = get_session_state(_TESTER)
        for i in range(_MAX_LOG_ENTRIES + 5):
            state.append_log(f"entry-{i}")
        assert len(state.log_entries) == _MAX_LOG_ENTRIES
        # The oldest entries should be gone; newest should be present
        assert f"entry-{_MAX_LOG_ENTRIES + 4}" in state.log_entries
        assert "entry-0" not in state.log_entries


class TestStateExpiresWithItsToken:
    """Audit F-044: state outlived the sign-in that created it."""

    def test_state_older_than_any_valid_token_is_dropped(self, monkeypatch: object) -> None:
        import spectre.web.planning_state as ps

        clock = [1000.0]
        monkeypatch.setattr(ps.time, "monotonic", lambda: clock[0])  # type: ignore[attr-defined]
        clear_session_state(_ALICE)
        get_session_state(_ALICE).udl_password = "udl-secret"
        clock[0] += ps._STATE_MAX_AGE_S + 1
        get_session_state(_BOB)   # any access prunes
        assert not ps.has_session_state(_ALICE)
        clear_session_state(_BOB)

    def test_the_lifetime_matches_the_session_cookie(self) -> None:
        import spectre.web.planning_state as ps
        from spectre.web import auth

        assert ps._STATE_MAX_AGE_S == auth._SESSION_MAX_AGE
