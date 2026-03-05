"""SIPC runtime settings — dataclass with environment variable overrides."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class Settings:
    """Runtime configuration for a SIPC session.

    Values are populated from environment variables where available,
    with sensible defaults for local development.
    """

    stk_scenario_path: str = field(
        default_factory=lambda: os.environ.get("SIPC_SCENARIO_PATH", "")
    )
    log_level: str = field(
        default_factory=lambda: os.environ.get("SIPC_LOG_LEVEL", "INFO")
    )
    log_dir: str = field(
        default_factory=lambda: os.environ.get("SIPC_LOG_DIR", "logs")
    )
    integration_tests_enabled: bool = field(
        default_factory=lambda: os.environ.get("STK_INTEGRATION_TESTS", "0") == "1"
    )
    stk_root: str = field(
        default_factory=lambda: os.environ.get(
            "SIPC_STK_ROOT",
            r"C:\Program Files\AGI\STK 13",
        )
    )
    secret_key: str = field(
        default_factory=lambda: os.environ.get("SECRET_KEY", "")
    )
    database_url: str = field(
        default_factory=lambda: os.environ.get(
            "DATABASE_URL", "sqlite+aiosqlite:///./sipc.db"
        )
    )
    sipc_admin_user: str = field(
        default_factory=lambda: os.environ.get("SIPC_ADMIN_USER", "admin")
    )
    sipc_admin_pass: str = field(
        default_factory=lambda: os.environ.get("SIPC_ADMIN_PASS", "")
    )


def get_settings() -> Settings:
    """Return a Settings instance populated from the current environment."""
    return Settings()
