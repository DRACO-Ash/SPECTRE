"""Tests for runtime configuration resolution and fail-closed validation.

These cover the App Store deployment contract: the port and data directory
resolve in code (never from a baked ENV), and an unusable secret or an
unwritable volume stops the boot rather than degrading silently.
"""

from __future__ import annotations

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

    def test_sqlite_does_not_land_on_the_persistent_volume(
        self, clean_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """This asserted the opposite until it caused a failed deploy.

        Putting SQLite on the injected mount looks right (durable storage) and
        is wrong: the App Store volume is object-storage backed and provides no
        POSIX byte-range locking, so the first transaction fails with an opaque
        disk I/O error. Durability comes from the POSTGRESQL add-on instead.
        """
        monkeypatch.setenv("STORAGE_MOUNT_PATH", "/data")
        assert _resolve_database_url() != "sqlite+aiosqlite:////data/spectre.db"


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

    def test_rejects_unwritable_directory_with_errno_and_remedy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The boot message must carry the errno and the fsGroup remedy.

        The failure is injected rather than produced by chmod, because the test
        suite also runs as root in the container image, where filesystem
        permissions are bypassed and a chmod-based test silently skips.
        """
        def deny_write(self: Path, *args: object, **kwargs: object) -> None:
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(Path, "write_text", deny_write)
        with pytest.raises(ConfigurationError) as exc:
            validate_data_dir(str(tmp_path))
        message = str(exc.value)
        assert "errno 13" in message
        assert "fsGroup" in message

    def test_rejects_a_directory_that_cannot_be_created(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A read-only parent must fail the boot, not be silently ignored."""
        def deny_mkdir(self: Path, *args: object, **kwargs: object) -> None:
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(Path, "mkdir", deny_mkdir)
        with pytest.raises(ConfigurationError, match="cannot be created"):
            validate_data_dir(str(tmp_path / "nope"))


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


class TestDatabaseUrlNormalisation:
    """The POSTGRESQL add-on injects a synchronous URL; the async engine needs a driver."""

    @pytest.mark.parametrize(
        ("injected", "expected"),
        [
            ("postgresql://u:p@host:5432/db", "postgresql+asyncpg://u:p@host:5432/db"),
            ("postgres://u:p@host:5432/db", "postgresql+asyncpg://u:p@host:5432/db"),
            ("postgresql+asyncpg://u:p@host/db", "postgresql+asyncpg://u:p@host/db"),
            ("sqlite:///./local.db", "sqlite+aiosqlite:///./local.db"),
            ("sqlite+aiosqlite:///./local.db", "sqlite+aiosqlite:///./local.db"),
        ],
    )
    def test_driver_is_filled_in(self, injected: str, expected: str) -> None:
        from spectre.config.settings import _normalise_database_url

        assert _normalise_database_url(injected) == expected

    def test_injected_url_is_normalised_end_to_end(
        self, clean_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@db.internal:5432/spectre")
        assert _resolve_database_url().startswith("postgresql+asyncpg://")

    def test_uses_sqlite_detects_the_backend(self) -> None:
        from spectre.config.settings import uses_sqlite

        assert uses_sqlite("sqlite+aiosqlite:////data/spectre.db") is True
        assert uses_sqlite("postgresql+asyncpg://u@h/db") is False


class TestSqliteSupportProbe:
    """A write probe alone gives a false pass on an object-storage volume."""

    def test_accepts_a_normal_filesystem(self, tmp_path: Path) -> None:
        from spectre.config.settings import validate_sqlite_support

        validate_sqlite_support(tmp_path)

    def test_leaves_no_probe_files_behind(self, tmp_path: Path) -> None:
        from spectre.config.settings import validate_sqlite_support

        validate_sqlite_support(tmp_path)
        assert list(tmp_path.iterdir()) == []

    def test_fails_closed_when_sqlite_cannot_operate(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Reproduces the deploy failure: writes succeed, SQLite does not.

        The App Store FILE_STORAGE volume is S3-backed and does not provide the
        POSIX byte-range locking SQLite needs, so table creation died with an
        opaque disk I/O error after the boot log had already said WRITABLE.
        """
        import sqlite3

        from spectre.config.settings import ConfigurationError, validate_sqlite_support

        def no_locking(*args: object, **kwargs: object) -> None:
            raise sqlite3.OperationalError("disk I/O error")

        monkeypatch.setattr(sqlite3, "connect", no_locking)
        with pytest.raises(ConfigurationError) as exc:
            validate_sqlite_support(tmp_path)
        message = str(exc.value)
        assert "disk I/O error" in message
        assert "POSTGRESQL" in message, "the message must name the remedy"
        assert "locking" in message, "the message must name the cause"


class TestSqliteNeverLandsOnTheObjectStore:
    """The deploy failure that cost two cycles: SQLite on an S3-backed mount.

    The database location and the persistent volume are separate concerns. The
    volume is object storage and cannot host SQLite at all, so the two must
    never be derived from the same variable again.
    """

    def test_sqlite_dir_ignores_the_injected_mount(
        self, clean_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from spectre.config.settings import _resolve_sqlite_dir

        monkeypatch.setenv("STORAGE_MOUNT_PATH", "/data")
        assert _resolve_sqlite_dir() != "/data"
        assert not _resolve_sqlite_dir().startswith("/data")

    def test_sqlite_url_is_not_placed_on_the_injected_mount(
        self, clean_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("STORAGE_MOUNT_PATH", "/data")
        url = _resolve_database_url()
        assert url.startswith("sqlite+aiosqlite:///")
        # Compare the actual parent directory. A substring test would match any
        # path ending ".../data/spectre.db", including the correct local one.
        db_path = Path(url.split("sqlite+aiosqlite:///", 1)[1])
        assert db_path.parent != Path("/data"), "the database must not sit on object storage"

    def test_data_dir_still_follows_the_injected_mount(
        self, clean_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The volume is still used, just not for the database."""
        monkeypatch.setenv("STORAGE_MOUNT_PATH", "/data")
        assert _resolve_data_dir() == "/data"

    def test_an_injected_database_url_wins_over_sqlite(
        self, clean_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("STORAGE_MOUNT_PATH", "/data")
        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db:5432/spectre")
        from spectre.config.settings import uses_sqlite

        url = _resolve_database_url()
        assert uses_sqlite(url) is False
        assert url.startswith("postgresql+asyncpg://")

    def test_sqlite_dir_can_be_overridden_explicitly(
        self, clean_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from spectre.config.settings import _resolve_sqlite_dir

        monkeypatch.setenv("SPECTRE_SQLITE_DIR", "/srv/db")
        monkeypatch.setenv("STORAGE_MOUNT_PATH", "/data")
        assert _resolve_sqlite_dir() == "/srv/db"


class TestLibpqParameterTranslation:
    """asyncpg rejects libpq query parameters with a bare TypeError.

    The managed PostgreSQL add-on injects a libpq-style URL, typically carrying
    ``?sslmode=require``. Passing that through crashed the pod at connect time
    with `connect() got an unexpected keyword argument 'sslmode'`, which reads
    as a code defect rather than a configuration mismatch.
    """

    def test_sslmode_require_encrypts_without_verifying(self) -> None:
        """libpq's `require` means encrypt, NOT verify.

        asyncpg's ssl=True builds a verifying context, which rejects the
        private certificate authorities managed databases normally use. The
        translation must follow libpq, or a correct URL fails to connect.
        """
        import ssl as ssl_module

        from spectre.config.settings import split_database_url

        url, args = split_database_url(
            "postgresql+asyncpg://u:p@host:5432/db?sslmode=require"
        )
        assert "sslmode" not in url
        context = args["ssl"]
        assert isinstance(context, ssl_module.SSLContext)
        assert context.check_hostname is False
        assert context.verify_mode == ssl_module.CERT_NONE

    def test_sslmode_disable_turns_tls_off(self) -> None:
        from spectre.config.settings import split_database_url

        _url, args = split_database_url(
            "postgresql+asyncpg://u:p@host/db?sslmode=disable"
        )
        assert args["ssl"] is False

    @pytest.mark.parametrize("mode", ["allow", "prefer"])
    def test_negotiating_modes_leave_the_default_alone(self, mode: str) -> None:
        from spectre.config.settings import split_database_url

        _url, args = split_database_url(
            f"postgresql+asyncpg://u:p@host/db?sslmode={mode}"
        )
        assert "ssl" not in args, "asyncpg negotiates by default; do not override"

    @pytest.mark.parametrize("mode", ["verify-ca", "verify-full"])
    def test_verifying_modes_build_an_ssl_context(self, mode: str) -> None:
        import ssl as ssl_module

        from spectre.config.settings import split_database_url

        _url, args = split_database_url(
            f"postgresql+asyncpg://u:p@host/db?sslmode={mode}"
        )
        context = args["ssl"]
        assert isinstance(context, ssl_module.SSLContext)
        assert context.check_hostname is (mode == "verify-full")
        assert context.verify_mode == ssl_module.CERT_REQUIRED

    def test_every_libpq_only_parameter_is_stripped(self) -> None:
        from spectre.config.settings import split_database_url

        url, _args = split_database_url(
            "postgresql+asyncpg://u:p@host/db"
            "?sslmode=require&target_session_attrs=read-write"
            "&application_name=spectre&options=-c%20statement_timeout%3D0"
        )
        for banned in ("sslmode", "target_session_attrs", "application_name", "options"):
            assert banned not in url, f"{banned} would raise TypeError in asyncpg"

    def test_non_libpq_parameters_survive(self) -> None:
        from spectre.config.settings import split_database_url

        url, _args = split_database_url(
            "postgresql+asyncpg://u:p@host/db?sslmode=require&prepared_statement_cache_size=0"
        )
        assert "prepared_statement_cache_size=0" in url

    def test_connect_timeout_is_translated_not_dropped(self) -> None:
        from spectre.config.settings import split_database_url

        _url, args = split_database_url(
            "postgresql+asyncpg://u:p@host/db?connect_timeout=15"
        )
        assert args["timeout"] == 15.0

    def test_sqlite_urls_are_untouched(self) -> None:
        from spectre.config.settings import split_database_url

        url, args = split_database_url("sqlite+aiosqlite:////app/data/spectre.db")
        assert url == "sqlite+aiosqlite:////app/data/spectre.db"
        assert args == {}

    def test_the_add_on_url_shape_end_to_end(
        self, clean_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Exactly what the platform injected, from raw value to connect args."""
        from spectre.config.settings import split_database_url

        monkeypatch.setenv(
            "DATABASE_URL", "postgresql://spectre:pw@pg.internal:5432/spectre?sslmode=require"
        )
        url, args = split_database_url(_resolve_database_url())
        assert url.startswith("postgresql+asyncpg://")
        assert "sslmode" not in url
        assert args["ssl"] is not None, "TLS intent must survive the translation"
