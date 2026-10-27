"""Every runtime setting is read by the application (audit F-157).

``Settings.log_dir`` was populated from SPECTRE_LOG_DIR and never read, and
the structlog configuration it was meant for was never called. An operator
who set the variable expected per-run JSON logs that were never written.
"""

from __future__ import annotations

import re
from dataclasses import fields
from pathlib import Path

from spectre.config.settings import Settings

_ROOT = Path(__file__).resolve().parents[2]
_SETTINGS = _ROOT / "spectre" / "config" / "settings.py"


def _application_source() -> str:
    return "\n".join(
        p.read_text(encoding="utf-8")
        for p in sorted((_ROOT / "spectre").rglob("*.py"))
        if p != _SETTINGS
    )


def test_every_settings_field_is_read_outside_the_settings_module() -> None:
    source = _application_source()
    unread = [f.name for f in fields(Settings) if not re.search(rf"\.{f.name}\b", source)]
    assert unread == []


def test_the_dead_logging_package_is_gone() -> None:
    assert not (_ROOT / "spectre" / "app_logging").exists()
