"""Domain layer exceptions."""

from __future__ import annotations


class DomainError(Exception):
    """Base exception for domain logic errors."""


class InvalidTleError(DomainError):
    """Raised when a TLE string fails validation."""


class NoInterceptWindowError(DomainError):
    """Raised when no feasible intercept window can be found."""


class PlanningRunError(DomainError):
    """Raised when a planning run fails for an unrecoverable reason."""
