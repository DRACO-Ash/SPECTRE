"""Integration tests for StkComSession — require a live STK 13 installation.

These tests are skipped unless ``STK_INTEGRATION_TESTS=1`` is set in the
environment. They must be run on Windows with STK 13 installed and licensed.

Usage::

    $env:STK_INTEGRATION_TESTS = "1"
    pytest tests/integration/ -v
"""

from __future__ import annotations

import pytest

from sipc.stk_adapter.com_session import StkComSession


@pytest.mark.integration
class TestStkComSession:
    """Live COM tests for StkComSession.

    All tests in this class require STK 13 to be installed and running.
    """

    def test_connect_attaches_to_running_stk(self) -> None:
        """connect('') should attach to an already-running STK instance."""
        session = StkComSession()
        # Will raise StkConnectionError if STK is not running — expected in CI
        session.connect("")
        assert session._root is not None
        session.disconnect()

    def test_disconnect_releases_references(self) -> None:
        """disconnect() should set internal COM references to None."""
        session = StkComSession()
        session.connect("")
        session.disconnect()
        assert session._app is None
        assert session._root is None

    def test_get_scenario_epoch_returns_datetime(self) -> None:
        """get_scenario_epoch() should return a UTC-aware datetime."""

        session = StkComSession()
        session.connect("")
        epoch = session.get_scenario_epoch()
        assert epoch.tzinfo is not None
        session.disconnect()
