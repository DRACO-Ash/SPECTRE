"""STK adapter exceptions."""

from __future__ import annotations


class StkAdapterError(Exception):
    """Base exception for all STK adapter errors."""


class StkConnectionError(StkAdapterError):
    """Raised when a connection to STK cannot be established or is lost."""


class StkObjectNotFoundError(StkAdapterError):
    """Raised when a requested STK object (satellite, facility, etc.) does not exist."""


class StkCommandError(StkAdapterError):
    """Raised when an STK Connect command returns an error."""
