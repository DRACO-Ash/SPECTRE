"""One JSON object per line on standard output: the Bluestaq App Store logging standard.

WHY

The platform reads a container's standard output as its log stream and checks
every line. Its standard, advisory from release 0.48.4 and blocking from
1 December 2026, is one JSON object per line on stdout and nothing at all on
stderr, errors included. SPECTRE wrote plain text to stderr through
``logging.basicConfig`` and, when it refused to boot, let Python print the
traceback there too, so the check saw nothing on stdout and 115 lines on stderr.

WHAT A LINE CARRIES

``timestamp`` (UTC, milliseconds), ``severity_text`` and ``severity_number``
(TRACE 1, DEBUG 5, INFO 9, WARN 13, ERROR 17, FATAL 21), ``body``, and
``attributes``, a flat object. ``trace_id`` and ``span_id`` appear only when a
caller supplies them. Fields passed with ``extra=`` land in ``attributes``,
nested mappings flattened to dotted keys and every value made JSON-safe. An
exception goes to ``exception.type``, ``exception.message`` and
``exception.stacktrace``.

The standard forbids a service name, tenant or application identifiers, and
any Authorization or Cookie value, token or query string. Nothing here adds
one, and an attribute whose key names one is dropped rather than written, so a
careless ``extra=`` cannot put a credential in the log.

WHO CALLS IT

``configure_logging`` is idempotent. The entrypoint calls it before anything
can fail, with the process hooks on, so a boot refusal and an uncaught
exception are JSON lines on stdout. The app's lifespan calls
``ensure_logging``, which installs the handler when the app runs under a bare
server and leaves a host that logs its own way, such as a test runner, alone. ``uvicorn_log_config`` gives uvicorn the same
formatter and handler, so its own lines are JSON on stdout too.
"""

from __future__ import annotations

import json
import logging
import math
import sys
import threading
from collections.abc import Mapping
from datetime import UTC, datetime
from types import TracebackType
from typing import Any

# The standard's severity pairs, highest first so the first threshold a
# record's level reaches names it. WARNING is WARN and CRITICAL is FATAL.
_SEVERITIES: tuple[tuple[int, str, int], ...] = (
    (logging.CRITICAL, "FATAL", 21),
    (logging.ERROR, "ERROR", 17),
    (logging.WARNING, "WARN", 13),
    (logging.INFO, "INFO", 9),
    (logging.DEBUG, "DEBUG", 5),
)
_TRACE = ("TRACE", 1)

# Every attribute a bare LogRecord has, so what is left on a record is what a
# caller passed with ``extra=``. ``color_message`` is uvicorn's ANSI-coloured
# copy of the message, which is noise in a JSON line.
_RECORD_FIELDS = frozenset(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {
    "message", "asctime", "color_message",
}

# Promoted to the top level when a caller supplies them, never left in attributes.
_TOP_LEVEL_EXTRAS = ("trace_id", "span_id")

# An attribute whose key contains one of these is dropped: a credential, a
# token or a query string never reaches the log, whoever passed it.
_FORBIDDEN_KEY_PARTS = (
    "authorization", "cookie", "password", "passwd", "secret", "token", "csrf",
    "session", "api_key", "apikey", "query",
)
# Identity the platform supplies itself and the standard forbids repeating.
_FORBIDDEN_KEYS = frozenset({"service.name", "service.instance.id", "app.id", "app_id"})
_FORBIDDEN_KEY_PREFIXES = ("tenant",)

# httpx writes every outbound request's full URL, query string included, at
# INFO. SPECTRE's outbound calls (UDL, GCAT) carry their filters in the query,
# and the standard admits no query string, so these libraries log WARN and up.
_QUIETENED_LIBRARIES = ("httpx", "httpcore")

#: The name of the stdout handler, so configure_logging can find its own.
HANDLER_NAME = "spectre-json-stdout"


def severity_of(levelno: int) -> tuple[str, int]:
    """Return the standard's (severity_text, severity_number) for a stdlib level."""
    for threshold, text, number in _SEVERITIES:
        if levelno >= threshold:
            return text, number
    return _TRACE


def utc_timestamp(created: float) -> str:
    """*created* (seconds since the epoch) as UTC to the millisecond: ``2026-11-17T09:30:15.123Z``."""
    return datetime.fromtimestamp(created, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _forbidden(key: str) -> bool:
    lowered = key.lower()
    return (
        lowered in _FORBIDDEN_KEYS
        or lowered.startswith(_FORBIDDEN_KEY_PREFIXES)
        or any(part in lowered for part in _FORBIDDEN_KEY_PARTS)
    )


def _scalar(value: object) -> str | int | float | bool | None:
    """*value* as a JSON scalar: a non-finite float or any object becomes its text."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    return str(value)


def _json_safe(value: object) -> Any:
    """*value* as a JSON-safe attribute value: a scalar, or a list of scalars."""
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_scalar(item) for item in value]
    return _scalar(value)


def flatten_attributes(values: Mapping[str, object], prefix: str = "") -> dict[str, Any]:
    """Flatten *values* into one level of dotted keys, dropping forbidden ones."""
    flat: dict[str, Any] = {}
    for raw_key, value in values.items():
        key = f"{prefix}{raw_key}"
        if _forbidden(key):
            continue
        if isinstance(value, Mapping):
            flat.update(flatten_attributes(value, prefix=f"{key}."))
        else:
            flat[key] = _json_safe(value)
    return flat


def _exception_attributes(exc_type: type[BaseException], exc: BaseException, stacktrace: str) -> dict[str, str]:
    module = exc_type.__module__
    name = exc_type.__qualname__ if module == "builtins" else f"{module}.{exc_type.__qualname__}"
    return {
        "exception.type": name,
        "exception.message": str(exc),
        "exception.stacktrace": stacktrace,
    }


class JsonFormatter(logging.Formatter):
    """Format a record as one line of the App Store logging standard."""

    def format(self, record: logging.LogRecord) -> str:
        try:
            body = record.getMessage()
        except (TypeError, ValueError):
            # A call whose arguments do not fit its format string. Write the
            # format string rather than lose the line or print to stderr.
            body = str(record.msg)
        severity_text, severity_number = severity_of(record.levelno)
        line: dict[str, Any] = {
            "timestamp": utc_timestamp(record.created),
            "severity_text": severity_text,
            "severity_number": severity_number,
            "body": body,
        }
        extras = {key: value for key, value in vars(record).items() if key not in _RECORD_FIELDS}
        for key in _TOP_LEVEL_EXTRAS:
            if key in extras:
                line[key] = _scalar(extras.pop(key))
        attributes: dict[str, Any] = {"logger.name": record.name}
        attributes.update(flatten_attributes(extras))
        if record.exc_info:
            exc_type, exc_value, _ = record.exc_info
            if exc_type is not None and exc_value is not None:
                attributes.update(_exception_attributes(exc_type, exc_value, self.formatException(record.exc_info)))
        if record.stack_info:
            attributes["code.stacktrace"] = record.stack_info
        line["attributes"] = attributes
        return json.dumps(line, separators=(",", ":"))


def _unformattable_line(record: logging.LogRecord, exc: Exception) -> str:
    """A minimal standard line for a record the formatter could not render."""
    severity_text, severity_number = severity_of(record.levelno)
    return json.dumps({
        "timestamp": utc_timestamp(record.created),
        "severity_text": severity_text,
        "severity_number": severity_number,
        "body": str(record.msg) if isinstance(record.msg, str) else "unformattable log record",
        "attributes": {"logger.name": record.name, "log.format_error": type(exc).__name__},
    }, separators=(",", ":"))


class StdoutHandler(logging.Handler):
    """Write each formatted record to standard output, one line, flushed.

    ``sys.stdout`` is read at every emit rather than captured once, so a test
    that captures stdout sees the lines, and so a replaced stream is honoured.
    A failure to write is swallowed: ``logging.Handler.handleError`` would print
    a traceback to stderr, which the standard forbids.
    """

    def __init__(self, level: int = logging.NOTSET) -> None:
        super().__init__(level)
        self.set_name(HANDLER_NAME)
        self.setFormatter(JsonFormatter())

    def emit(self, record: logging.LogRecord) -> None:
        stream = sys.stdout
        if stream is None:
            return
        try:
            line = self.format(record)
        # BLE001: a record that cannot be formatted (an extra whose str() raises)
        # must neither crash the caller nor reach stderr; a minimal line says so.
        except Exception as exc:  # noqa: BLE001
            line = _unformattable_line(record, exc)
        try:
            stream.write(line + "\n")
            stream.flush()
        except (OSError, ValueError):
            # A closed or broken stdout has nowhere left to report to.
            return


def _json_handler(handlers: list[logging.Handler]) -> logging.Handler | None:
    return next((handler for handler in handlers if isinstance(handler, StdoutHandler)), None)


def _is_plain_stderr_handler(handler: logging.Handler) -> bool:
    """True for a bare StreamHandler on stderr, as ``basicConfig`` would install."""
    return type(handler) is logging.StreamHandler and handler.stream in (sys.stderr, sys.__stderr__)


def _log_uncaught(
    exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None,
) -> None:
    """``sys.excepthook``: an uncaught exception is a FATAL line on stdout, not a stderr traceback."""
    log = logging.getLogger("spectre")
    if issubclass(exc_type, KeyboardInterrupt):
        log.warning("Interrupted")
        return
    log.critical("Uncaught exception, the process is exiting: %s", exc, exc_info=(exc_type, exc, tb))


def _log_thread_exception(args: threading.ExceptHookArgs) -> None:
    """``threading.excepthook``: a thread that dies logs ERROR rather than printing to stderr."""
    if args.exc_value is None:
        return
    logging.getLogger("spectre").error(
        "Uncaught exception in thread %s", getattr(args.thread, "name", "unknown"),
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
    )


def _log_unraisable(unraisable: Any) -> None:
    """``sys.unraisablehook``: Python's "Exception ignored in" note, as an ERROR line."""
    exc = unraisable.exc_value
    exc_info = (unraisable.exc_type, exc, unraisable.exc_traceback) if exc is not None else None
    logging.getLogger("spectre").error(
        "Exception ignored in %r: %s", unraisable.object, unraisable.err_msg or "", exc_info=exc_info,
    )


def install_process_hooks() -> None:
    """Route Python's own stderr writers through logging: uncaught exceptions and warnings.

    Only the process's owner calls this (the entrypoint). A test runner keeps
    hooks of its own and must not have them replaced from inside a test.
    """
    sys.excepthook = _log_uncaught
    threading.excepthook = _log_thread_exception
    sys.unraisablehook = _log_unraisable
    logging.captureWarnings(True)
    # Reached only when no handler exists anywhere on a logger's path; its
    # default writes to stderr.
    logging.lastResort = StdoutHandler(logging.WARNING)


def configure_logging(level: str | int = "INFO", *, process_hooks: bool = False) -> logging.Handler:
    """Send every log record to stdout as one JSON line. Idempotent.

    Installs one :class:`StdoutHandler` on the root logger, or reuses the one
    already there, and removes any bare stderr handler ``basicConfig`` left.
    Other handlers, a test runner's capture among them, are left alone. httpx
    and httpcore are held at WARN, because their INFO line is a full URL.

    Args:
        level: The root level, a name such as ``"INFO"`` or a number. An
            unknown name falls back to INFO.
        process_hooks: Also route uncaught exceptions, thread exceptions,
            unraisable exceptions and warnings through logging.

    Returns:
        The stdout handler on the root logger.
    """
    numeric = level if isinstance(level, int) else getattr(logging, str(level).upper(), logging.INFO)
    if not isinstance(numeric, int):
        numeric = logging.INFO
    root = logging.getLogger()
    for stale in [h for h in root.handlers if _is_plain_stderr_handler(h)]:
        root.removeHandler(stale)
    handler = _json_handler(root.handlers)
    if handler is None:
        handler = StdoutHandler()
        root.addHandler(handler)
    root.setLevel(numeric)
    for library in _QUIETENED_LIBRARIES:
        logging.getLogger(library).setLevel(max(numeric, logging.WARNING))
    if process_hooks:
        install_process_hooks()
    return handler


def ensure_logging(level: str | int = "INFO") -> logging.Handler | None:
    """Configure as :func:`configure_logging` does, unless the host already logs its own way.

    The app's lifespan calls this. Under the entrypoint the JSON handler is
    already on the root logger and this only sets the level. Under a bare
    server that left the root logger empty it installs the handler. Under a
    host that put handlers of its own on the root logger, a test runner's
    capture among them, it changes nothing, as ``basicConfig`` did before it,
    so a test's captured stdout holds only what the test itself printed.

    Returns:
        The stdout handler, or None when the host's own handlers were left in charge.
    """
    root = logging.getLogger()
    if any(not isinstance(h, StdoutHandler) and not _is_plain_stderr_handler(h) for h in root.handlers):
        return None
    return configure_logging(level)


def uvicorn_log_config(level: str = "INFO") -> dict[str, Any]:
    """A ``logging.config.dictConfig`` for uvicorn: its loggers and root on the JSON stdout handler.

    uvicorn applies this before it imports the app, and without one it
    installs its own text handlers on stderr. ``uvicorn``, ``uvicorn.error``
    and ``uvicorn.access`` propagate to the root logger, which carries the one
    stdout handler, so every line from every logger leaves by the same route.
    The access logger stays silent: the entrypoint turns it off because its
    line carries the query string, and the app writes its own request line.
    """
    name = str(level).upper()
    if not isinstance(getattr(logging, name, None), int):
        name = "INFO"
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "handlers": {
            "stdout": {"()": f"{__name__}.StdoutHandler"},
        },
        "root": {"level": name, "handlers": ["stdout"]},
        "loggers": {
            "uvicorn": {"level": name, "handlers": [], "propagate": True},
            "uvicorn.error": {"level": name, "handlers": [], "propagate": True},
            "uvicorn.access": {"level": name, "handlers": [], "propagate": True},
        },
    }
