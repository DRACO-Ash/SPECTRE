"""The event log: the one channel between builders and the board (VH-366-B).

A builder appends one JSON line per fact. The board replays the log into its state. Three rules keep a late or
repeated line from moving a forecast:
  1. A line that fails the schema is reported with its line number and skipped, and an event with any problem is
     refused whole, never half applied.
  2. An event whose id was applied before changes nothing (the same event twice is the same as once).
  3. An event stamped before the board's last read, and not applied then, is refused as stale, because applying it
     now would move a figure that someone has already read.
Standard library only, so the pack drops into a project of any language.
"""
import copy
import datetime
import json
import os
import re
import tempfile

ITEM_STATES = ("open", "allocated", "needscheck", "decision", "input", "answered", "inbuild", "queued", "held",
               "blocked", "needscost", "built", "closed", "released", "done", "removed")
GATE_STATUS = ("pending", "running", "pass", "fail")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,63}$")
REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
EMPTY = {"applied": {}, "last_read": None, "items": {}, "accuracy": [], "gates": {}, "lanes": {}}


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0


def parse_time(text):
    """UTC time from an ISO 8601 string ending in Z, or None."""
    if not isinstance(text, str) or not text.endswith("Z"):
        return None
    try:
        return datetime.datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError:
        return None


def validate(event):
    """Every problem with one event, together. An empty list means it is well formed."""
    if not isinstance(event, dict):
        return ["the line is not a JSON object"]
    out = []
    if not isinstance(event.get("id"), str) or not ID_RE.match(event["id"]):
        out.append("id is missing or not 3 to 64 letters, digits and . _ : -")
    if parse_time(event.get("at")) is None:
        out.append("at is missing or not an ISO 8601 UTC time ending in Z")
    kind = event.get("kind")
    if kind == "item_state":
        if not isinstance(event.get("ref"), str) or not REF_RE.match(event["ref"]):
            out.append("ref is missing or malformed")
        if event.get("state") not in ITEM_STATES:
            out.append("state is not one of " + ", ".join(ITEM_STATES))
    elif kind == "accuracy":
        if not isinstance(event.get("ref"), str) or not REF_RE.match(event["ref"]):
            out.append("ref is missing or malformed")
        if not _num(event.get("est")) or not _num(event.get("actual")):
            out.append("est and actual must both be numbers above zero")
    elif kind == "gate":
        if not isinstance(event.get("key"), str) or not REF_RE.match(event["key"]):
            out.append("key is missing or malformed")
        if event.get("status") not in GATE_STATUS:
            out.append("status is not one of " + ", ".join(GATE_STATUS))
    elif kind == "lanes":
        if not isinstance(event.get("release"), str) or not event["release"].strip():
            out.append("release is missing")
        for f in ("lanes", "priced", "elapsed"):
            if not _num(event.get(f)):
                out.append(f + " must be a number above zero")
    else:
        out.append("kind is not one of item_state, accuracy, gate, lanes")
    return out


def apply_event(state, event):
    """Returns (state, outcome, why). The input state is never changed. Outcomes: applied, duplicate, stale, refused."""
    problems = validate(event)
    if problems:
        return state, "refused", "; ".join(problems)
    if event["id"] in state["applied"]:
        return state, "duplicate", "this id was applied before, so nothing changes"
    last = parse_time(state.get("last_read"))
    if last is not None and parse_time(event["at"]) < last:
        return state, "stale", "stamped " + event["at"] + ", before the board's last read at " + state["last_read"]
    new = copy.deepcopy(state)
    k = event["kind"]
    if k == "item_state":
        new["items"][event["ref"]] = {"state": event["state"], "at": event["at"]}
    elif k == "accuracy":
        new["accuracy"].append({"ref": event["ref"], "est": event["est"], "actual": event["actual"], "at": event["at"],
                                "kind": event.get("row_kind", "item")})
    elif k == "gate":
        new["gates"][event["key"]] = {"status": event["status"], "at": event["at"]}
    else:
        new["lanes"][event["release"]] = {"lanes": event["lanes"], "priced": event["priced"], "elapsed": event["elapsed"], "at": event["at"]}
    new["applied"][event["id"]] = event["at"]
    return new, "applied", ""


def read_log(text):
    """Events from JSON Lines text. Returns (events, problems) where a bad line is a problem with its line number."""
    events, problems = [], []
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            events.append((n, json.loads(line)))
        except ValueError:
            problems.append(f"line {n}: not JSON, skipped")
    return events, problems


def replay(state, log_text, now):
    """Applies the log in file order. Returns (state, report) with a count per outcome and every refusal listed."""
    state = copy.deepcopy(state) if state else copy.deepcopy(EMPTY)
    for k, v in EMPTY.items():
        state.setdefault(k, copy.deepcopy(v))
    events, bad = read_log(log_text)
    report = {"applied": 0, "duplicate": 0, "stale": 0, "refused": 0, "problems": list(bad)}
    for n, ev in events:
        state, outcome, why = apply_event(state, ev)
        report[outcome] += 1
        if outcome in ("stale", "refused"):
            report["problems"].append(f"line {n}: {outcome}: {why}")
    state["last_read"] = now
    return state, report


def save_state(path, state):
    """Writes the state beside its target and renames it over, so a failed write never leaves half a file."""
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".state-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(state, f, indent=1, sort_keys=True)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
