"""Unit tests for spectre.config.settings."""

from __future__ import annotations

import os

from spectre.config.settings import Settings, get_settings


class TestSettings:
    """Tests for Settings dataclass."""

    def test_defaults(self) -> None:
        """Settings should have sensible defaults when no env vars are set."""
        env_keys = ["SPECTRE_LOG_LEVEL", "SPECTRE_LOG_DIR"]
        original = {k: os.environ.pop(k, None) for k in env_keys}
        try:
            s = Settings()
            assert s.log_level == "INFO"
            assert s.log_dir == "logs"
        finally:
            for k, v in original.items():
                if v is not None:
                    os.environ[k] = v

    def test_log_level_from_env(self, monkeypatch: object) -> None:
        """SPECTRE_LOG_LEVEL env var should override the default."""
        import pytest
        with pytest.MonkeyPatch().context() as mp:
            mp.setenv("SPECTRE_LOG_LEVEL", "DEBUG")
            s = Settings()
            assert s.log_level == "DEBUG"

    def test_get_settings_returns_settings_instance(self) -> None:
        """get_settings() should return a Settings instance."""
        s = get_settings()
        assert isinstance(s, Settings)
