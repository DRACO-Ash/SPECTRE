"""Tests for runtime configuration resolution and fail-closed validation.

These cover the App Store deployment contract: the port and data directory
resolve in code (never from a baked ENV), and an unusable secret or an
unwritable volume stops the boot rather than degrading silently.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from spectre.config.settings import (
    DEFAULT_PORT,
    ConfigurationError,
    Settings,
    _resolve_data_dir,
    _resolve_database_url,
    _resolve_port,
    get_settings,
    validate_data_dir,
    validate_secret_key,
)


@pytest.fixture()
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every variable these tests care about, so defaults are exercised."""
    for name in (
        "PORT", "SPECTRE_DATA_DIR", "STORAGE_MOUNT_PATH", "DATABASE_URL", "SECRET_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


class TestPortResolution:
    def test_defaults_to_8080(self, clean_env: None) -> None:
        """The platform sets containerPort 8080; the code default must match."""
        assert _resolve_port() == DEFAULT_PORT == 8080

    def test_honours_injected_port(self, clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PORT", "9090")
        assert _resolve_port() == 9090

    @pytest.mark.parametrize("bad", ["", "   ", "not-a-number", "0", "-1", "70000"])
    def test_falls_back_to_8080_on_unusable_value(
        self, clean_env: None, monkeypatch: pytest.MonkeyPatch, bad: str
    ) -> None:
        """An unusable PORT must not crash the app or bind somewhere unexpected."""
        monkeypatch.setenv("PORT", bad)
        assert _resolve_port() == DEFAULT_PORT


class TestDataDirResolution:
    def test_explicit_variable_wins(self, clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SPECTRE_DATA_DIR", "/explicit")
        monkeypatch.setenv("STORAGE_MOUNT_PATH", "/injected")
        assert _resolve_data_dir() == "/explicit"

    def test_platform_injected_mount_is_used(
        self, clean_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The FILE_STORAGE add-on injects STORAGE_MOUNT_PATH; it must be honoured."""
        monkeypatch.setenv("STORAGE_MOUNT_PATH", "/data")
        assert _resolve_data_dir() == "/data"

    def test_falls_back_to_local_directory(self, clean_env: None) -> None:
        assert _resolve_data_dir().endswith("data")


class TestDatabaseUrlResolution:
    def test_explicit_url_wins(self, clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://host/db")
        assert _resolve_database_url() == "postgresql+asyncpg://host/db"

    def test_sqlite_lands_inside_the_data_directory(
        self, clean_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SQLite must sit on the persistent volume, not the ephemeral layer."""
        monkeypatch.setenv("STORAGE_MOUNT_PATH", "/data")
        assert _resolve_database_url() == "sqlite+aiosqlite:////data/spectre.db"


class TestSecretKeyValidation:
    def test_accepts_a_real_secret(self) -> None:
        validate_secret_key("k" * 32)

    @pytest.mark.parametrize(
        "bad",
        ["", "   ", "change-me", "CHANGE-ME", "change-me-to-a-random-string", "secret", "short"],
    )
    def test_rejects_unusable_secrets(self, bad: str) -> None:
        """Missing, placeholder or short keys let an attacker forge sessions."""
        with pytest.raises(ConfigurationError):
            validate_secret_key(bad)

    def test_error_names_the_variable(self) -> None:
        with pytest.raises(ConfigurationError, match="SECRET_KEY"):
            validate_secret_key("")


class TestDataDirValidation:
    def test_creates_and_accepts_a_writable_directory(self, tmp_path: Path) -> None:
        target = tmp_path / "nested" / "data"
        assert validate_data_dir(str(target)) == target.resolve()
        assert target.is_dir()

    def test_leaves_no_probe_file_behind(self, tmp_path: Path) -> None:
        validate_data_dir(str(tmp_path))
        assert list(tmp_path.iterdir()) == []

    def test_rejects_filesystem_root(self) -> None:
        with pytest.raises(ConfigurationError, match="filesystem root"):
            validate_data_dir("/")

    @pytest.mark.skipif(os.getuid() == 0, reason="root bypasses filesystem permissions")
    def test_rejects_unwritable_directory_with_errno_and_remedy(self, tmp_path: Path) -> None:
        """The 503/boot message must carry the errno and the fsGroup remedy."""
        locked = tmp_path / "locked"
        locked.mkdir()
        locked.chmod(0o555)
        try:
            with pytest.raises(ConfigurationError) as exc:
                validate_data_dir(str(locked))
            assert "errno" in str(exc.value)
            assert "fsGroup" in str(exc.value)
        finally:
            locked.chmod(0o755)


class TestSettings:
    def test_get_settings_reads_current_environment(
        self, clean_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SECRET_KEY", "s" * 32)
        monkeypatch.setenv("PORT", "8080")
        settings = get_settings()
        assert isinstance(settings, Settings)
        assert settings.secret_key == "s" * 32
        assert settings.port == 8080
