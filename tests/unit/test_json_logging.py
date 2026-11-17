"""The JSON log line: the Bluestaq App Store logging standard (0.48.4).

One object per line on stdout, nothing on stderr; timestamp in UTC to the
millisecond; the six severity pairs; a flat attributes object with the
exception in exception.*; no credential, query string or platform identity.
"""

from __future__ import annotations

import json
import logging
import logging.config
import sys
import threading
import warnings
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest

from spectre.web import json_logging
from spectre.web.json_logging import (
    JsonFormatter,
    StdoutHandler,
    configure_logging,
    ensure_logging,
    flatten_attributes,
    install_process_hooks,
    severity_of,
    uvicorn_log_config,
)
from tests._log_standard import assert_standard_line, standard_lines


def _record(level: int = logging.INFO, msg: str = "hello %s", args: tuple[object, ...] = ("world",),
            **extra: object) -> logging.LogRecord:
    record = logging.LogRecord("spectre.test", level, __file__, 1, msg, args, None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def _format(record: logging.LogRecord) -> dict[str, Any]:
    return assert_standard_line(JsonFormatter().format(record))


@pytest.fixture()
def root_restored() -> Iterator[logging.Logger]:
    """The root logger, with its handlers and level put back afterwards."""
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield root
    root.handlers[:] = handlers
    root.setLevel(level)


@pytest.fixture()
def hooks_restored(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Process hooks put back after a test installs SPECTRE's."""
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(sys, "unraisablehook", sys.unraisablehook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    monkeypatch.setattr(logging, "lastResort", logging.lastResort)
    yield
    logging.captureWarnings(False)


class TestTheLine:
    def test_the_fields_and_their_types(self) -> None:
        line = _format(_record())
        assert line["body"] == "hello world"
        assert line["severity_text"] == "INFO"
        assert line["severity_number"] == 9
        assert line["attributes"] == {"logger.name": "spectre.test"}
        assert "trace_id" not in line
        assert "span_id" not in line

    def test_one_line_even_when_the_message_has_newlines(self) -> None:
        text = JsonFormatter().format(_record(msg="a\nforged line", args=()))
        assert "\n" not in text
        assert json.loads(text)["body"] == "a\nforged line"

    def test_the_timestamp_is_utc_to_the_millisecond(self) -> None:
        record = _record()
        record.created = datetime(2026, 11, 17, 9, 30, 15, 123456, tzinfo=UTC).timestamp()
        assert _format(record)["timestamp"] == "2026-11-17T09:30:15.123Z"

    @pytest.mark.parametrize(("level", "text", "number"), [
        (5, "TRACE", 1),
        (logging.DEBUG, "DEBUG", 5),
        (logging.INFO, "INFO", 9),
        (logging.WARNING, "WARN", 13),
        (logging.ERROR, "ERROR", 17),
        (logging.CRITICAL, "FATAL", 21),
    ])
    def test_the_severity_pairs(self, level: int, text: str, number: int) -> None:
        assert severity_of(level) == (text, number)
        line = _format(_record(level=level))
        assert (line["severity_text"], line["severity_number"]) == (text, number)

    def test_a_level_between_two_takes_the_lower(self) -> None:
        assert severity_of(logging.INFO + 5) == ("INFO", 9)
        assert severity_of(logging.CRITICAL + 10) == ("FATAL", 21)

    def test_a_format_mismatch_still_writes_a_line(self) -> None:
        line = _format(_record(msg="%d widgets", args=("not a number",)))
        assert line["body"] == "%d widgets"


class TestTheAttributes:
    def test_extra_fields_land_in_attributes(self) -> None:
        attributes = _format(_record(run_id="RUN_1", window_count=3, ratio=0.5, ok=True, none=None))["attributes"]
        assert attributes["run_id"] == "RUN_1"
        assert attributes["window_count"] == 3
        assert attributes["ratio"] == 0.5
        assert attributes["ok"] is True
        assert attributes["none"] is None

    def test_nested_mappings_are_flattened_to_dotted_keys(self) -> None:
        attributes = _format(_record(http={"request": {"method": "GET"}, "status": 200}))["attributes"]
        assert attributes["http.request.method"] == "GET"
        assert attributes["http.status"] == 200
        assert not any(isinstance(value, dict) for value in attributes.values())

    def test_values_are_made_json_safe(self) -> None:
        attributes = _format(_record(when=datetime(2026, 1, 1, tzinfo=UTC), bad=float("nan"),
                                     items=("a", 1, object), raw=b"x"))["attributes"]
        assert attributes["when"] == "2026-01-01 00:00:00+00:00"
        assert attributes["bad"] == "nan"
        assert attributes["items"][:2] == ["a", 1]
        assert isinstance(attributes["items"][2], str)
        assert attributes["raw"] == "b'x'"

    @pytest.mark.parametrize("key", [
        "authorization", "Cookie", "set_cookie", "csrf_token", "session_token", "api_key", "password",
        "client_secret", "url.query", "service.name", "tenant_id", "tenant", "app_id",
    ])
    def test_a_forbidden_key_is_dropped(self, key: str) -> None:
        assert flatten_attributes({key: "SENSITIVE", "kept": 1}) == {"kept": 1}

    def test_trace_and_span_ids_go_to_the_top_level(self) -> None:
        line = _format(_record(trace_id="4bf92f3577b34da6a3ce929d0e0e4736", span_id="00f067aa0ba902b7"))
        assert line["trace_id"] == "4bf92f3577b34da6a3ce929d0e0e4736"
        assert line["span_id"] == "00f067aa0ba902b7"
        assert "trace_id" not in line["attributes"]

    def test_uvicorn_colour_copy_is_not_an_attribute(self) -> None:
        assert "color_message" not in _format(_record(color_message="\x1b[1mhi\x1b[0m"))["attributes"]


class TestExceptions:
    def test_an_exception_is_three_attributes(self) -> None:
        try:
            raise ValueError("boom")
        except ValueError:
            record = _record(level=logging.ERROR)
            record.exc_info = sys.exc_info()
        attributes = _format(record)["attributes"]
        assert attributes["exception.type"] == "ValueError"
        assert attributes["exception.message"] == "boom"
        assert attributes["exception.stacktrace"].startswith("Traceback (most recent call last)")
        assert "ValueError: boom" in attributes["exception.stacktrace"]

    def test_a_non_builtin_exception_is_named_in_full(self) -> None:
        from spectre.config.settings import ConfigurationError

        record = _record(level=logging.CRITICAL)
        record.exc_info = (ConfigurationError, ConfigurationError("no key"), None)
        assert _format(record)["attributes"]["exception.type"] == "spectre.config.settings.ConfigurationError"


class TestConfigure:
    def test_lines_go_to_stdout_and_nothing_to_stderr(
        self, root_restored: logging.Logger, capsys: pytest.CaptureFixture[str],
    ) -> None:
        configure_logging("INFO")
        logging.getLogger("spectre.test").warning("disk %d%% full", 91)
        captured = capsys.readouterr()
        assert captured.err == ""
        (line,) = [ln for ln in standard_lines(captured.out) if ln["attributes"]["logger.name"] == "spectre.test"]
        assert (line["severity_text"], line["severity_number"], line["body"]) == ("WARN", 13, "disk 91% full")

    def test_idempotent(self, root_restored: logging.Logger) -> None:
        first = configure_logging("INFO")
        second = configure_logging("DEBUG")
        assert first is second
        assert sum(isinstance(h, StdoutHandler) for h in root_restored.handlers) == 1
        assert root_restored.level == logging.DEBUG

    def test_ensure_installs_on_an_empty_root(self, root_restored: logging.Logger) -> None:
        root_restored.handlers[:] = []
        handler = ensure_logging("INFO")
        assert isinstance(handler, StdoutHandler)
        assert root_restored.handlers == [handler]

    def test_ensure_reuses_the_entrypoints_handler(self, root_restored: logging.Logger) -> None:
        root_restored.handlers[:] = []
        installed = configure_logging("INFO")
        assert ensure_logging("DEBUG") is installed
        assert root_restored.level == logging.DEBUG

    def test_ensure_leaves_a_host_that_logs_its_own_way_alone(self, root_restored: logging.Logger) -> None:
        own = logging.NullHandler()
        root_restored.handlers[:] = [own]
        level = root_restored.level
        assert ensure_logging("DEBUG") is None
        assert root_restored.handlers == [own]
        assert root_restored.level == level

    def test_http_client_libraries_are_held_at_warn(self, root_restored: logging.Logger) -> None:
        """Their INFO line is the outbound URL, query string and all."""
        saved = {name: logging.getLogger(name).level for name in ("httpx", "httpcore")}
        try:
            configure_logging("DEBUG")
            assert not logging.getLogger("httpx").isEnabledFor(logging.INFO)
            assert not logging.getLogger("httpcore").isEnabledFor(logging.INFO)
            assert logging.getLogger("httpx").isEnabledFor(logging.WARNING)
        finally:
            for name, level in saved.items():
                logging.getLogger(name).setLevel(level)

    def test_an_unknown_level_falls_back_to_info(self, root_restored: logging.Logger) -> None:
        configure_logging("LOUD")
        assert root_restored.level == logging.INFO

    def test_a_basic_config_stderr_handler_is_removed_and_others_kept(self, root_restored: logging.Logger) -> None:
        stderr_handler = logging.StreamHandler(sys.stderr)
        other = logging.NullHandler()
        root_restored.addHandler(stderr_handler)
        root_restored.addHandler(other)
        configure_logging()
        assert stderr_handler not in root_restored.handlers
        assert other in root_restored.handlers

    def test_a_closed_stdout_is_not_reported_to_stderr(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    ) -> None:
        class Broken:
            def write(self, _text: str) -> int:
                raise OSError("closed")

            def flush(self) -> None:
                return None

        monkeypatch.setattr(sys, "stdout", Broken())
        StdoutHandler().emit(_record())
        assert capsys.readouterr().err == ""


    def test_an_unformattable_record_is_still_one_standard_line(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    ) -> None:
        class Unprintable:
            def __str__(self) -> str:
                raise RuntimeError("no text")

        StdoutHandler().emit(_record(level=logging.ERROR, msg="saving", args=(), thing=Unprintable()))
        captured = capsys.readouterr()
        assert captured.err == ""
        (line,) = standard_lines(captured.out)
        assert (line["severity_text"], line["body"]) == ("ERROR", "saving")
        assert line["attributes"]["log.format_error"] == "RuntimeError"


class TestProcessHooks:
    @pytest.mark.usefixtures("hooks_restored", "root_restored")
    def test_an_uncaught_exception_is_fatal_on_stdout(self, capsys: pytest.CaptureFixture[str]) -> None:
        configure_logging("INFO", process_hooks=True)
        try:
            raise RuntimeError("at boot")
        except RuntimeError:
            sys.excepthook(*sys.exc_info())
        captured = capsys.readouterr()
        assert captured.err == ""
        fatal = standard_lines(captured.out)[-1]
        assert fatal["severity_text"] == "FATAL"
        assert fatal["attributes"]["exception.type"] == "RuntimeError"
        assert fatal["attributes"]["exception.message"] == "at boot"

    @pytest.mark.usefixtures("hooks_restored", "root_restored")
    def test_a_python_warning_is_a_warn_line(self, capsys: pytest.CaptureFixture[str]) -> None:
        configure_logging("INFO")
        install_process_hooks()
        with warnings.catch_warnings():
            warnings.simplefilter("always")
            warnings.warn("deprecated thing", DeprecationWarning, stacklevel=1)
        captured = capsys.readouterr()
        assert captured.err == ""
        (line,) = [ln for ln in standard_lines(captured.out) if ln["attributes"]["logger.name"] == "py.warnings"]
        assert line["severity_text"] == "WARN"
        assert "deprecated thing" in line["body"]

    @pytest.mark.usefixtures("hooks_restored", "root_restored")
    def test_a_dying_thread_is_an_error_line(self, capsys: pytest.CaptureFixture[str]) -> None:
        configure_logging("INFO")
        install_process_hooks()

        def fail() -> None:
            raise KeyError("lost")

        worker = threading.Thread(target=fail, name="worker-1")
        worker.start()
        worker.join()
        captured = capsys.readouterr()
        assert captured.err == ""
        line = standard_lines(captured.out)[-1]
        assert line["severity_text"] == "ERROR"
        assert line["body"] == "Uncaught exception in thread worker-1"
        assert line["attributes"]["exception.type"] == "KeyError"

    @pytest.mark.usefixtures("hooks_restored", "root_restored")
    def test_an_interrupt_is_a_warning_not_a_fatal(self, capsys: pytest.CaptureFixture[str]) -> None:
        configure_logging("INFO", process_hooks=True)
        sys.excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)
        line = standard_lines(capsys.readouterr().out)[-1]
        assert (line["severity_text"], line["body"]) == ("WARN", "Interrupted")


class TestUvicornConfig:
    def test_routes_uvicorn_through_the_one_stdout_handler(self) -> None:
        """Checked as configuration: applying it here would close the test runner's own handlers.

        The entrypoint's subprocess tests apply it for real.
        """
        config = uvicorn_log_config("debug")
        factory = logging.config.DictConfigurator(config).resolve(config["handlers"]["stdout"]["()"])
        assert factory is StdoutHandler
        assert config["root"] == {"level": "DEBUG", "handlers": ["stdout"]}
        for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
            assert config["loggers"][name] == {"level": "DEBUG", "handlers": [], "propagate": True}

    def test_an_unknown_level_is_info(self) -> None:
        assert uvicorn_log_config("LOUD")["root"]["level"] == "INFO"

    def test_existing_loggers_are_not_disabled(self) -> None:
        assert uvicorn_log_config()["disable_existing_loggers"] is False


def test_the_handler_name_is_stable() -> None:
    assert StdoutHandler().get_name() == json_logging.HANDLER_NAME
