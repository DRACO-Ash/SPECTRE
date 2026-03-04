"""Unit tests for sipc.config.settings."""

from __future__ import annotations

import os

from sipc.config.settings import Settings, get_settings


class TestSettings:
    """Tests for Settings dataclass."""

    def test_defaults(self) -> None:
        """Settings should have sensible defaults when no env vars are set."""
        env_keys = ["SIPC_SCENARIO_PATH", "SIPC_LOG_LEVEL", "SIPC_LOG_DIR",
                    "STK_INTEGRATION_TESTS", "SIPC_STK_ROOT"]
        original = {k: os.environ.pop(k, None) for k in env_keys}
        try:
            s = Settings()
            assert s.stk_scenario_path == ""
            assert s.log_level == "INFO"
            assert s.log_dir == "logs"
            assert s.integration_tests_enabled is False
        finally:
            for k, v in original.items():
                if v is not None:
                    os.environ[k] = v

    def test_log_level_from_env(self, monkeypatch: object) -> None:
        """SIPC_LOG_LEVEL env var should override the default."""
        import pytest
        with pytest.MonkeyPatch().context() as mp:
            mp.setenv("SIPC_LOG_LEVEL", "DEBUG")
            s = Settings()
            assert s.log_level == "DEBUG"

    def test_integration_tests_enabled_when_flag_set(self, monkeypatch: object) -> None:
        """STK_INTEGRATION_TESTS=1 should enable integration tests flag."""
        import pytest
        with pytest.MonkeyPatch().context() as mp:
            mp.setenv("STK_INTEGRATION_TESTS", "1")
            s = Settings()
            assert s.integration_tests_enabled is True

    def test_get_settings_returns_settings_instance(self) -> None:
        """get_settings() should return a Settings instance."""
        s = get_settings()
        assert isinstance(s, Settings)
