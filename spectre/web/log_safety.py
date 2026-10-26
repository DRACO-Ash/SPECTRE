"""Make operator-supplied values safe to put in a log line.

WHY

A log file is read by people and by machines, and both of them trust line
boundaries. A value that reaches a log unescaped can carry its own newline and
forge an entry:

    username = "alice\\n2026-10-22 09:00:00 spectre.web.auth INFO Successful login: root"

One ``logger.info("Successful login: %s", username)`` then writes two lines,
the second of which is indistinguishable from a real one. SonarQube reports
this as pythonsecurity:S5145, and it is a real finding rather than a
formality: SPECTRE's audit trail is the record of who asked the system for
what, and an attacker who can write into it can also hide in it.

WHAT THIS DOES

``log_safe`` replaces every non-printable character, newlines and carriage
returns among them, with a single space, collapses the result, and truncates
it. The value still reads naturally for every legitimate input, because a real
username, satellite name or method label contains nothing it touches.

It deliberately does NOT escape or quote. A quoted value that still contains a
newline is still two lines; removing the line break is the fix, and anything
further would make ordinary log lines harder to read for no gain.
"""

from __future__ import annotations

# Long enough for any legitimate username, satellite designator or method
# label; short enough that a pasted payload cannot flood the record.
_DEFAULT_LIMIT = 120

_ELLIPSIS = "..."


def log_safe(value: object, limit: int = _DEFAULT_LIMIT) -> str:
    """Return *value* as a single-line, printable, bounded string.

    Args:
        value: Anything. It is rendered with ``str()`` first, so a number or
            an enum is accepted and returned unchanged.
        limit: Maximum length of the result, truncation marker included.

    Returns:
        A string safe to interpolate into a log record: no newlines, no
        carriage returns, no other control characters, and never longer than
        *limit*.
    """
    text = str(value)
    cleaned = "".join(char if char.isprintable() else " " for char in text)
    # Collapse the runs a replacement can create, so a payload of newlines does
    # not become a payload of spaces.
    collapsed = " ".join(cleaned.split())
    if len(collapsed) <= limit:
        return collapsed
    # A limit no wider than the marker has no room for text and marker both;
    # appending it anyway returned more than *limit* characters (audit F-262).
    if limit <= len(_ELLIPSIS):
        return collapsed[: max(0, limit)]
    return collapsed[: limit - len(_ELLIPSIS)] + _ELLIPSIS
