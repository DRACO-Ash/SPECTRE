"""An sslmode the code does not know is an error, not "encrypt without verifying".

Audit F-153. Any unrecognised sslmode, a typo such as ``verify_full`` among
them, fell into the ``require`` branch and built a context with CERT_NONE,
silently downgrading a requested verification to none. Client certificate
parameters were dropped without a word.
"""

from __future__ import annotations

import logging
import ssl

import pytest

from spectre.config.settings import ConfigurationError, split_database_url

_BASE = "postgresql+asyncpg://u:p@host:5432/db"


@pytest.mark.parametrize("mode", ["verify_full", "verifyfull", "requre", "strict"])
def test_an_unknown_mode_is_refused(mode: str) -> None:
    with pytest.raises(ConfigurationError, match="sslmode"):
        split_database_url(f"{_BASE}?sslmode={mode}")


def test_require_still_encrypts_without_verifying() -> None:
    _url, args = split_database_url(f"{_BASE}?sslmode=require")
    assert args["ssl"].verify_mode is ssl.CERT_NONE


def test_a_dropped_client_certificate_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        split_database_url(f"{_BASE}?sslmode=require&sslcert=/c.pem&sslkey=/k.pem")
    assert "sslcert" in caplog.text and "sslkey" in caplog.text
