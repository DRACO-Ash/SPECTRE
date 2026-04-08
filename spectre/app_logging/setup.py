"""SPECTRE application logging — structlog configuration with run_id correlation."""

from __future__ import annotations

import logging
from pathlib import Path

import structlog
from typing import cast


def configure_logging(run_id: str, log_level: str = "INFO", log_dir: str = "logs") -> None:
    """Configure structlog for a planning run.

    Sets up two sinks:
    - Console: human-readable coloured output via structlog's ConsoleRenderer.
    - File: JSON-lines output in ``log_dir/<run_id>.jsonl`` for post-run analysis.

    The ``run_id`` is bound to every log record emitted during the run.

    Args:
        run_id: Unique identifier for the current planning run (e.g. ``RUN_20260304_001``).
        log_level: Minimum log level string (``DEBUG``, ``INFO``, ``WARNING``, ``ERROR``).
        log_dir: Directory path where per-run JSON log files are written.
    """
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    # Ensure log directory exists
    Path(log_dir).mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(numeric_level)

    # Add a per-run file handler (JSON-lines).  We add it directly rather than
    # via basicConfig so this works even after uvicorn has already installed its
    # own stderr handler (basicConfig is a no-op once any handler exists).
    log_path = Path(log_dir) / f"{run_id}.jsonl"
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(numeric_level)
    file_handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(file_handler)

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Bind run_id to all subsequent log calls in this thread/context
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(run_id=run_id)


def get_logger(name: str) -> structlog.BoundLogger:
    """Return a structlog bound logger for *name*.

    Args:
        name: Typically ``__name__`` of the calling module.

    Returns:
        A structlog BoundLogger with the current contextvars (including run_id) pre-bound.
    """
    return cast(structlog.BoundLogger, structlog.get_logger(name))
