"""Unit tests for domain and stk_adapter exception classes."""

from __future__ import annotations

import pytest

from sipc.domain.exceptions import (
    DomainError,
    InvalidTleError,
    NoInterceptWindowError,
    PlanningRunError,
)
from sipc.stk_adapter.exceptions import (
    StkAdapterError,
    StkCommandError,
    StkConnectionError,
    StkObjectNotFoundError,
)


class TestDomainExceptions:
    """Tests for sipc.domain.exceptions."""

    def test_domain_error_is_exception(self) -> None:
        with pytest.raises(DomainError):
            raise DomainError("base error")

    def test_invalid_tle_error_is_domain_error(self) -> None:
        with pytest.raises(DomainError):
            raise InvalidTleError("bad TLE")

    def test_no_intercept_window_error_message(self) -> None:
        exc = NoInterceptWindowError("no windows found")
        assert "no windows found" in str(exc)

    def test_planning_run_error_is_domain_error(self) -> None:
        with pytest.raises(DomainError):
            raise PlanningRunError("run failed")


class TestStkAdapterExceptions:
    """Tests for sipc.stk_adapter.exceptions."""

    def test_stk_adapter_error_is_exception(self) -> None:
        with pytest.raises(StkAdapterError):
            raise StkAdapterError("adapter error")

    def test_stk_connection_error_is_adapter_error(self) -> None:
        with pytest.raises(StkAdapterError):
            raise StkConnectionError("connection failed")

    def test_stk_object_not_found_error_message(self) -> None:
        exc = StkObjectNotFoundError("B_SAT_Alpha not found")
        assert "B_SAT_Alpha" in str(exc)

    def test_stk_command_error_is_adapter_error(self) -> None:
        with pytest.raises(StkAdapterError):
            raise StkCommandError("command failed")
