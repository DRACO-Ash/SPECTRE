"""The README's quick start works, and hands out no usable signing key.

Audit F-056: both quick starts told operators to set SECRET_KEY to a
published 34-character string the fail-closed guard accepted, because the
placeholder list held a different wording and the length floor is 16.

Audit F-064: the quick start ran a console script no install creates, mapped
port 8000 while the app listens on 8080, asked for an install extra that does
not exist, and gave Python 3.14 as the minimum against 3.12 everywhere else.
"""

from __future__ import annotations

import re

import pytest

from spectre.config.settings import ConfigurationError, validate_secret_key
from tests.unit.test_deployment_contract import _repo_only

_LITERAL = re.compile(r"""SECRET_KEY\s*=\s*"?([^"\s\\]+)"?|SECRET_KEY="([^"]+)\"""")


def _literals() -> list[str]:
    found: list[str] = []
    for name in ("README.md", ".env.example"):
        for a, b in _LITERAL.findall(_repo_only(name).read_text(encoding="utf-8")):
            value = (a or b).strip()
            if value and not value.startswith("$"):
                found.append(value)
    return found


def test_no_documented_key_is_accepted() -> None:
    for literal in _literals():
        with pytest.raises(ConfigurationError):
            validate_secret_key(literal)


@pytest.mark.parametrize("key", ["change-me-to-a-long-random-string", "CHANGE-ME-please-0123456789", "my-changeme-key-0001"])
def test_any_change_me_key_is_refused(key: str) -> None:
    with pytest.raises(ConfigurationError):
        validate_secret_key(key)


def test_the_readme_quick_start_matches_the_app() -> None:
    readme = _repo_only("README.md").read_text(encoding="utf-8")
    assert "spectre-serve" not in readme
    assert "8000:" not in readme and "localhost:8000" not in readme
    assert '".[dev]"' not in readme
    assert "python -m spectre.web._entrypoint" in readme
    assert "-p 8080:8080" in readme
    assert re.search(r"\|\s*Python\s*\|\s*3\.12\s*\|", readme)
