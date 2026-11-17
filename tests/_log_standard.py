"""The Bluestaq App Store logging standard, as a test can check one line of it.

Shared by the formatter's unit tests, the request-line integration test and
the entrypoint's subprocess tests, so all three hold a line to the same rule.
"""

from __future__ import annotations

import json
import re
from typing import Any

SEVERITY_PAIRS = {"TRACE": 1, "DEBUG": 5, "INFO": 9, "WARN": 13, "ERROR": 17, "FATAL": 21}
REQUIRED_FIELDS = {"timestamp", "severity_text", "severity_number", "body", "attributes"}
OPTIONAL_FIELDS = {"trace_id", "span_id"}
# UTC, to the millisecond, with the zone written as Z.
TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
FORBIDDEN_ATTRIBUTES = ("service.name", "tenant", "app.id", "authorization", "cookie", "url.query")


def assert_standard_line(line: str) -> dict[str, Any]:
    """Parse *line* and assert it is one object under the standard; return it."""
    record = json.loads(line)
    assert isinstance(record, dict), line
    assert record.keys() >= REQUIRED_FIELDS, line
    assert record.keys() <= REQUIRED_FIELDS | OPTIONAL_FIELDS, line
    assert TIMESTAMP.match(record["timestamp"]), record["timestamp"]
    assert SEVERITY_PAIRS.get(record["severity_text"]) == record["severity_number"], line
    assert isinstance(record["body"], str), line
    attributes = record["attributes"]
    assert isinstance(attributes, dict), line
    for key, value in attributes.items():
        assert not isinstance(value, dict), f"attributes must be flat: {key}"
        assert not any(part in key.lower() for part in FORBIDDEN_ATTRIBUTES), key
    return record


def standard_lines(text: str) -> list[dict[str, Any]]:
    """Every non-empty line of *text*, each asserted to be under the standard."""
    return [assert_standard_line(line) for line in text.splitlines() if line.strip()]
