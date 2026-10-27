""".env.example lists every variable the settings module reads, truthfully.

Audit F-182. SPECTRE_SQLITE_DIR, SPECTRE_COOKIE_SECURE,
SPECTRE_DB_POOL_RECYCLE, SPECTRE_LOG_DIR and APPSTORE_DAST_SCAN were read but
absent, and the file and a docstring said SQLite lives in the data
directory, when it lives under ./data or SPECTRE_SQLITE_DIR on the
container's own filesystem and is ephemeral there.
"""

from __future__ import annotations

import re

from spectre.config import settings
from tests.unit.test_deployment_contract import _repo_only


def _names_read() -> set[str]:
    source = _repo_only("spectre/config/settings.py").read_text(encoding="utf-8")
    names = set(re.findall(r'os\.environ\.get\("([A-Z_]+)"', source))
    names.add(settings._DAST_SCAN_FLAG)
    return names


def test_every_variable_read_is_documented() -> None:
    example = _repo_only(".env.example").read_text(encoding="utf-8")
    missing = sorted(n for n in _names_read() if not re.search(rf"\b{n}\b", example))
    assert missing == []


def test_sqlite_is_not_said_to_live_in_the_data_directory() -> None:
    example = _repo_only(".env.example").read_text(encoding="utf-8")
    assert "SQLite inside the\n# resolved data directory" not in example
    assert "SPECTRE_SQLITE_DIR" in example
    assert "inside the resolved data directory" not in (settings._resolve_database_url.__doc__ or "")
