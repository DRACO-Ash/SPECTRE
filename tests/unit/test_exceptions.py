"""Unit tests for domain exception classes."""

from __future__ import annotations

import pytest

from spectre.domain.exceptions import (
    DomainError,
    InvalidTleError,
    NoInterceptWindowError,
    PlanningRunError,
)


class TestDomainExceptions:
    """Tests for spectre.domain.exceptions."""

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
