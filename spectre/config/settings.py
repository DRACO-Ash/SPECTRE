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

import os
from dataclasses import dataclass, field
from pathlib import Path

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


def _resolve_database_url() -> str:
    """Return the database URL, resolved at runtime.

    An explicit ``DATABASE_URL`` wins (the POSTGRESQL add-on injects one).
    Otherwise SQLite is placed inside the resolved data directory so the
    database lands on the persistent volume rather than the ephemeral layer.
    """
    explicit = os.environ.get("DATABASE_URL", "").strip()
    if explicit:
        return explicit
    return f"sqlite+aiosqlite:///{Path(_resolve_data_dir()) / 'spectre.db'}"


def _resolve_port() -> int:
    """Return the listen port: ``PORT`` if injected and valid, else 8080."""
    raw = os.environ.get("PORT", "").strip()
    if not raw:
        return DEFAULT_PORT
    try:
        port = int(raw)
    except ValueError:
        return DEFAULT_PORT
    return port if 1 <= port <= 65535 else DEFAULT_PORT


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
