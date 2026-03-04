"""QThread worker base classes for running STK calls off the UI thread."""

from __future__ import annotations

import logging
import traceback
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThread, QThreadPool, Signal, Slot

logger = logging.getLogger(__name__)


class WorkerSignals(QObject):
    """Signals emitted by a :class:`Worker` instance.

    Attributes:
        started: Emitted when the worker begins execution.
        finished: Emitted when the worker completes (success or failure).
        result: Emitted with the return value on success.
        error: Emitted with ``(exception_type, exception, traceback_str)`` on failure.
        progress: Emitted with an integer percentage (0-100) for long operations.
    """

    started: Signal = Signal()
    finished: Signal = Signal()
    result: Signal = Signal(object)
    error: Signal = Signal(tuple)
    progress: Signal = Signal(int)


class Worker(QRunnable):
    """Generic QRunnable wrapper for executing a callable in the thread pool.

    Usage::

        def expensive_stk_call(session, run_id):
            return session.compute_access("B_SAT_Alpha", "R_SAT_Track01")

        worker = Worker(expensive_stk_call, session, run_id)
        worker.signals.result.connect(self.handle_result)
        worker.signals.error.connect(self.handle_error)
        QThreadPool.globalInstance().start(worker)

    Args:
        fn: The callable to execute in a worker thread.
        *args: Positional arguments forwarded to *fn*.
        **kwargs: Keyword arguments forwarded to *fn*.
    """

    def __init__(self, fn: Any, *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        """Execute the callable and emit result or error signals."""
        self.signals.started.emit()
        try:
            result = self._fn(*self._args, **self._kwargs)
            self.signals.result.emit(result)
        except Exception as exc:
            tb = traceback.format_exc()
            logger.error("Worker error: %s\n%s", exc, tb)
            self.signals.error.emit((type(exc), exc, tb))
        finally:
            self.signals.finished.emit()


class PlanningWorker(Worker):
    """Specialised worker for executing a :class:`~sipc.domain.scenario.ScenarioPlanner` run.

    Emits ``result`` with the list of :class:`~sipc.domain.models.InterceptWindow`
    objects on success.
    """
