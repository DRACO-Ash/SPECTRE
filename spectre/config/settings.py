"""SPECTRE runtime settings — dataclass with environment variable overrides.

Configuration contract
----------------------
Every deployment-injected value is resolved **in code**, never baked into the
container image with ``ENV``. A baked default always beats a code fallback
chain, which silently defeats the platform's injected value and sends writes to
the ephemeral container layer where they are lost on redeploy.

Resolution order for each value is: explicit SPECTRE variable, then the
platform-injected variable, then a safe local default.
"""

from __future__ import annotations

import contextlib
import os
import ssl
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from dotenv import load_dotenv

# Load .env from project root (two levels up from this file). Absent in the
# container image, which is intentional: the platform injects the environment.
_env_path = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(_env_path)

# The Bluestaq App Store sets containerPort 8080 and probes it. The value is
# read from the environment with 8080 as the default; it is never set via ENV
# in the Dockerfile, because that would override the platform's injection.
DEFAULT_PORT = 8080

# Placeholder values shipped in .env.example. Booting with one of these means
# the operator never set a real secret, so the app must refuse to start.
_PLACEHOLDER_SECRETS = frozenset({
    "change-me-to-a-random-string",
    "change-me",
    "changeme",
    "secret",
    "test",
})

# Minimum acceptable length for a session-signing key.
_MIN_SECRET_LENGTH = 16

# Valid TCP port range, per RFC 6335.
_MIN_PORT = 1
_MAX_PORT = 65535


def _resolve_data_dir() -> str:
    """Return the writable data directory, resolved at runtime.

    Order: ``SPECTRE_DATA_DIR`` (explicit), then ``STORAGE_MOUNT_PATH`` (the
    App Store FILE_STORAGE add-on), then a local ``data`` directory.
    """
    explicit = os.environ.get("SPECTRE_DATA_DIR", "").strip()
    if explicit:
        return explicit
    injected = os.environ.get("STORAGE_MOUNT_PATH", "").strip()
    if injected:
        return injected
    return str(Path.cwd() / "data")


def _normalise_database_url(url: str) -> str:
    """Return *url* with an async driver, whatever dialect spelling arrives.

    The POSTGRESQL add-on injects a synchronous URL (``postgresql://`` or the
    older ``postgres://``). SQLAlchemy's async engine cannot use either, so the
    driver is filled in here rather than requiring the operator to hand-edit a
    value the platform generated.
    """
    for prefix in ("postgresql+asyncpg://", "sqlite+aiosqlite://"):
        if url.startswith(prefix):
            return url
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://"):]
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://"):]
    if url.startswith("sqlite://"):
        return "sqlite+aiosqlite://" + url[len("sqlite://"):]
    return url


def _resolve_sqlite_dir() -> str:
    """Return the directory that holds the SQLite file.

    Deliberately NOT the FILE_STORAGE mount. That volume is object-storage
    backed and cannot host a SQLite database at all: it accepts file writes but
    provides no POSIX byte-range locking, so the first transaction dies with an
    opaque disk I/O error. The database therefore lives on the container's own
    filesystem, which is a real POSIX filesystem where SQLite works correctly.

    The consequence is that SQLite data is EPHEMERAL: it does not survive a
    redeploy or a restart. That is the correct trade for a fallback, because the
    alternative is a pod that cannot start. Attach the POSTGRESQL add-on for
    durable storage; boot logs a warning whenever this fallback is in use.
    """
    explicit = os.environ.get("SPECTRE_SQLITE_DIR", "").strip()
    if explicit:
        return explicit
    return str(Path.cwd() / "data")


def _resolve_database_url() -> str:
    """Return the database URL, resolved at runtime.

    An explicit ``DATABASE_URL`` wins (the POSTGRESQL add-on injects one).
    Otherwise SQLite is placed inside the resolved data directory.

    Without one, SQLite is used on the container's own filesystem, never on the
    FILE_STORAGE mount: see :func:`_resolve_sqlite_dir` for why that mount
    cannot host a database.
    """
    explicit = os.environ.get("DATABASE_URL", "").strip()
    if explicit:
        return _normalise_database_url(explicit)
    return f"sqlite+aiosqlite:///{Path(_resolve_sqlite_dir()) / 'spectre.db'}"


# libpq understands these query parameters; asyncpg does not, and passing one
# through raises TypeError at connect time. The managed PostgreSQL add-on
# injects a libpq-style URL, so they are translated or dropped here.
_LIBPQ_ONLY_PARAMS = frozenset({
    "sslmode", "sslrootcert", "sslcert", "sslkey", "sslcrl",
    "target_session_attrs", "options", "channel_binding", "gssencmode",
    "connect_timeout", "application_name", "fallback_application_name",
})

# sslmode values that mean "do not use TLS", "negotiate", and "require TLS".
_SSLMODE_DISABLED = frozenset({"disable"})
_SSLMODE_NEGOTIATE = frozenset({"allow", "prefer"})
_SSLMODE_VERIFYING = frozenset({"verify-ca", "verify-full"})


def split_database_url(url: str) -> tuple[str, dict[str, Any]]:
    """Return *url* stripped of libpq-only parameters, plus asyncpg connect args.

    The POSTGRESQL add-on hands over a URL written for libpq, typically with
    ``?sslmode=require``. asyncpg has no such keyword and fails the connection
    with a bare ``TypeError``, which surfaces as a crash-looping pod rather than
    anything resembling a configuration error. The TLS intent is preserved by
    translating it into asyncpg's ``ssl`` argument.
    """
    if not url.startswith("postgresql+asyncpg://"):
        return url, {}

    parts = urlsplit(url)
    query = parse_qsl(parts.query, keep_blank_values=True)
    kept = [(k, v) for k, v in query if k.lower() not in _LIBPQ_ONLY_PARAMS]
    dropped = {k.lower(): v for k, v in query if k.lower() in _LIBPQ_ONLY_PARAMS}

    connect_args: dict[str, Any] = {}
    sslmode = dropped.get("sslmode", "").strip().lower()
    cafile = dropped.get("sslrootcert") or None

    if sslmode in _SSLMODE_DISABLED:
        connect_args["ssl"] = False
    elif sslmode in _SSLMODE_VERIFYING:
        # verify-ca checks the chain; verify-full also checks the hostname.
        context = ssl.create_default_context(cafile=cafile)
        context.check_hostname = sslmode == "verify-full"
        context.verify_mode = ssl.CERT_REQUIRED
        connect_args["ssl"] = context
    elif sslmode and sslmode not in _SSLMODE_NEGOTIATE:
        # "require" means encrypt, and explicitly does NOT mean verify. Passing
        # asyncpg ssl=True would build a verifying context instead, which
        # rejects the private certificate authorities managed databases
        # normally use. Match libpq's semantics rather than asyncpg's default.
        context = ssl.create_default_context(cafile=cafile)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        connect_args["ssl"] = context

    if "connect_timeout" in dropped:
        with contextlib.suppress(ValueError):
            connect_args["timeout"] = float(dropped["connect_timeout"])

    cleaned = urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(kept, doseq=True), parts.fragment)
    )
    return cleaned, connect_args


def uses_sqlite(database_url: str) -> bool:
    """Return True when *database_url* points at a SQLite database."""
    return database_url.startswith("sqlite")


def _resolve_cookie_secure() -> bool:
    """Return whether the session cookie carries the ``Secure`` attribute.

    Secure by default. Without it the session cookie can be sent over plain
    HTTP and captured in transit. The only reason to disable it is a local
    HTTP development server or a test client, which is why turning it off
    requires an explicit opt-out rather than being inferred.
    """
    return os.environ.get("SPECTRE_COOKIE_SECURE", "true").strip().lower() not in {
        "false", "0", "no", "off",
    }


def _resolve_port() -> int:
    """Return the listen port: ``PORT`` if injected and valid, else 8080."""
    raw = os.environ.get("PORT", "").strip()
    if not raw:
        return DEFAULT_PORT
    try:
        port = int(raw)
    except ValueError:
        return DEFAULT_PORT
    return port if _MIN_PORT <= port <= _MAX_PORT else DEFAULT_PORT


@dataclass
class Settings:
    """Runtime configuration for a SPECTRE session.

    Values are populated from environment variables where available, with
    sensible defaults for local development.
    """

    log_level: str = field(
        default_factory=lambda: os.environ.get("SPECTRE_LOG_LEVEL", "INFO")
    )
    log_dir: str = field(
        default_factory=lambda: os.environ.get("SPECTRE_LOG_DIR", "logs")
    )
    secret_key: str = field(
        default_factory=lambda: os.environ.get("SECRET_KEY", "")
    )
    database_url: str = field(default_factory=_resolve_database_url)
    data_dir: str = field(default_factory=_resolve_data_dir)
    port: int = field(default_factory=_resolve_port)
    sqlite_dir: str = field(default_factory=_resolve_sqlite_dir)
    session_cookie_secure: bool = field(default_factory=_resolve_cookie_secure)
    spectre_admin_user: str = field(
        default_factory=lambda: os.environ.get("SPECTRE_ADMIN_USER", "admin")
    )
    spectre_admin_pass: str = field(
        default_factory=lambda: os.environ.get("SPECTRE_ADMIN_PASS", "")
    )


def get_settings() -> Settings:
    """Return a Settings instance populated from the current environment."""
    return Settings()


class ConfigurationError(RuntimeError):
    """Raised when the runtime configuration is unusable and boot must stop."""


def validate_secret_key(secret_key: str) -> None:
    """Raise :class:`ConfigurationError` unless *secret_key* is a real secret.

    Fails closed. A missing, placeholder, or trivially short signing key would
    let an attacker forge session and CSRF tokens, so the app must refuse to
    boot rather than start in a silently insecure state.
    """
    candidate = secret_key.strip()
    if not candidate:
        raise ConfigurationError(
            "SECRET_KEY is not set. Set it to a random string of at least "
            f"{_MIN_SECRET_LENGTH} characters (for example: "
            "python -c 'import secrets; print(secrets.token_urlsafe(32))')."
        )
    if candidate.lower() in _PLACEHOLDER_SECRETS:
        raise ConfigurationError(
            "SECRET_KEY is still set to the example placeholder value. "
            "Replace it with a real random secret before deploying."
        )
    if len(candidate) < _MIN_SECRET_LENGTH:
        raise ConfigurationError(
            f"SECRET_KEY is too short ({len(candidate)} characters). "
            f"Use at least {_MIN_SECRET_LENGTH} characters."
        )


def validate_data_dir(data_dir: str) -> Path:
    """Return *data_dir* as a validated, writable :class:`Path`.

    Checks the path is absolute-resolvable, is not the filesystem root, exists
    (creating it if needed), and actually accepts a write. An existence check
    alone passes on a read-only or root-owned mount, which is precisely the
    failure this guards against.
    """
    path = Path(data_dir).expanduser()
    try:
        path = path.resolve()
    except OSError as exc:  # pragma: no cover — defensive
        raise ConfigurationError(f"Data directory {data_dir!r} cannot be resolved: {exc}") from exc

    if path == Path(path.anchor):
        raise ConfigurationError(
            f"Data directory resolves to the filesystem root ({path}), which is not a valid store."
        )

    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ConfigurationError(
            f"Data directory {path} cannot be created: [errno {exc.errno}] {exc.strerror}"
        ) from exc

    probe = path / ".spectre-write-probe"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        raise ConfigurationError(
            f"Data directory {path} is not writable: [errno {exc.errno}] {exc.strerror}. "
            "If this is the App Store FILE_STORAGE add-on, the pod needs "
            "securityContext.fsGroup set so the non-root container can write to the volume."
        ) from exc

    return path


def validate_sqlite_support(data_dir: str | Path) -> None:
    """Raise :class:`ConfigurationError` if SQLite cannot operate in *data_dir*.

    A plain write probe is not sufficient and gives a false pass. An
    object-storage backed volume (the App Store FILE_STORAGE add-on is
    S3-backed) happily accepts ``write_text`` on a small file, then fails the
    moment SQLite needs POSIX byte-range locking or a rollback journal, which
    surfaces as an opaque ``disk I/O error`` partway through table creation.

    So this exercises the real operation: create a database, create a table
    inside a transaction, and roll it back.
    """
    # stdlib, imported here to keep the boot cost local to this check
    import sqlite3

    probe = Path(data_dir) / ".spectre-sqlite-probe.db"
    try:
        connection = sqlite3.connect(probe, timeout=5)
        try:
            connection.execute("CREATE TABLE probe (id INTEGER PRIMARY KEY, value TEXT)")
            connection.execute("INSERT INTO probe (value) VALUES ('ok')")
            connection.commit()
            connection.execute("DROP TABLE probe")
            connection.commit()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise ConfigurationError(
            f"SQLite cannot operate in {data_dir}: {exc}. "
            "This is the expected result on an object-storage backed volume such as "
            "the App Store FILE_STORAGE add-on, which does not support the POSIX "
            "file locking SQLite requires. Attach the POSTGRESQL add-on instead and "
            "let it inject DATABASE_URL; SPECTRE normalises the driver automatically."
        ) from exc
    finally:
        for leftover in (probe, Path(f"{probe}-journal"), Path(f"{probe}-wal"), Path(f"{probe}-shm")):
            with contextlib.suppress(OSError):  # best effort cleanup
                leftover.unlink(missing_ok=True)
