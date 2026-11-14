#!/usr/bin/env python3
"""Check SPECTRE's assumed UDL conjunction contract against live UDL (SPC-033).

SPECTRE reads UDL conjunction records with field names inferred from UDL's
published API and never seen live (spectre/web/udl_conjunction.py). This
probe asks UDL once for its query help and twice for records, and prints the
field names, value types and value shapes it finds, set against the names
SPECTRE reads. It prints no object names, no catalogue numbers other than
the one you pass, and no credentials, so its output can be pasted back.

Run it where UDL is reachable, with standard library Python only:

    UDL_USERNAME=... UDL_PASSWORD=... python3 -I scripts/udl_conjunction_probe.py 25544

or leave the variables unset to be prompted. Options: --mode REAL (default),
TEST, SIMULATED or EXERCISE; --max 5 records a side; --base to point at
another UDL host.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

DEFAULT_BASE = "https://unifieddatalibrary.com/udl"
PATH = "/conjunction"
SIDES = ("satNo1", "satNo2")

# The names SPECTRE reads today, by meaning. A live check confirms or corrects exactly these.
EXPECTED: dict[str, tuple[str, ...]] = {
    "record id": ("id",),
    "time of closest approach": ("tca", "TCA"),
    "miss distance": ("missDistance", "MISS_DISTANCE"),
    "miss distance unit": ("missDistanceUnit", "missDistanceUnits"),
    "collision probability": ("collisionProb", "COLLISION_PROBABILITY"),
    "data mode": ("dataMode",),
    "catalogue number, side 1": ("satNo1",),
    "catalogue number, side 2": ("satNo2",),
    "nested object, side 1": ("sat1", "stateVector1"),
    "nested object, side 2": ("sat2", "stateVector2"),
}
NESTED_EXPECTED = ("satNo", "objectName", "OBJECT_NAME")
# Fields whose values are shown as figures, since their unit is the question. Every other value shows its shape only.
SHOW_FIGURE = {"missDistance", "MISS_DISTANCE", "missDistanceUnit", "missDistanceUnits",
               "collisionProb", "COLLISION_PROBABILITY", "dataMode"}
TIMEOUT_S = 30.0


def _shape(value: Any) -> str:
    """The value's type and, for a string, its pattern with letters and digits masked."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return type(value).__name__
    if isinstance(value, str):
        masked = re.sub(r"[0-9]", "9", re.sub(r"[A-Za-z]", "a", value))
        return f"string like {masked[:40]!r}"
    if isinstance(value, dict):
        return f"object with {len(value)} fields"
    if isinstance(value, list):
        return f"list of {len(value)}"
    return type(value).__name__


def _describe(key: str, value: Any) -> str:
    if key in SHOW_FIGURE and isinstance(value, (int, float, str)) and not isinstance(value, bool):
        return f"{type(value).__name__} {str(value)[:24]!r}"
    return _shape(value)


def _get(base: str, path: str, params: dict[str, str], auth: str) -> tuple[int, Any, str]:
    """GET one URL: (status, parsed JSON or None, the first 300 characters when not JSON)."""
    query = f"?{urllib.parse.urlencode(params)}" if params else ""
    url = f"{base}{path}{query}"
    if not url.startswith("https://"):
        raise SystemExit("Refusing a base URL that is not https.")
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}", "Accept": "application/json"})
    try:
        # The scheme is checked as https above, so no file: or other scheme reaches urlopen.
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:  # nosec B310
            status, body = resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        status, body = exc.code, exc.read()
    except urllib.error.URLError as exc:
        return 0, None, f"no connection: {exc.reason}"
    text = body.decode("utf-8", errors="replace")
    try:
        return status, json.loads(text), ""
    except ValueError:
        return status, None, text[:300]


def _records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        for key in ("data", "results", "items"):
            if isinstance(payload.get(key), list):
                print(f"  reply wraps its records in {key!r}")
                return [r for r in payload[key] if isinstance(r, dict)]
    return []


def _report_query_help(base: str, auth: str) -> None:
    print("\n1. Query help")
    status, payload, text = _get(base, f"{PATH}/queryhelp", {}, auth)
    print(f"  HTTP {status}")
    if payload is None:
        print(f"  not JSON: {text!r}")
        return
    params = payload.get("parameters") if isinstance(payload, dict) else None
    if isinstance(params, list):
        names = sorted(str(p.get("name")) for p in params if isinstance(p, dict))
        print(f"  {len(names)} query parameters: {', '.join(names)}")
        for p in params:
            if isinstance(p, dict) and p.get("name") in {"tca", "missDistance", "satNo1", "satNo2", "dataMode"}:
                print(f"    {p.get('name')}: {str(p.get('description', ''))[:200]}")
    else:
        print(f"  reply is {_shape(payload)}; top-level keys: {sorted(payload)[:40] if isinstance(payload, dict) else '-'}")


def _report_records(side: str, records: list[dict[str, Any]], seen: dict[str, set[str]]) -> None:
    for n, rec in enumerate(records, 1):
        print(f"  record {n}: {len(rec)} fields")
        for key in sorted(rec):
            seen.setdefault(key, set()).add(_describe(key, rec[key]))
            if isinstance(rec[key], dict):
                inner = ", ".join(f"{k}: {_describe(k, v)}" for k, v in sorted(rec[key].items()))
                print(f"    {key}.{{{inner[:600]}}}")
    if not records:
        print(f"  no records with {side}")


def _report_expected(seen: dict[str, set[str]]) -> None:
    print("\n3. SPECTRE's assumed names against what UDL returned")
    for meaning, names in EXPECTED.items():
        found = [n for n in names if n in seen]
        mark = "FOUND" if found else "MISSING"
        detail = "; ".join(f"{n}: {', '.join(sorted(seen[n]))}" for n in found)
        print(f"  {mark:7} {meaning} ({' or '.join(names)}) {detail}")
    unread = sorted(k for k in seen if not any(k in n for n in EXPECTED.values()))
    print(f"\n  Fields UDL returned that SPECTRE does not read ({len(unread)}):")
    for key in unread:
        print(f"    {key}: {', '.join(sorted(seen[key]))}")
    print(f"\n  Nested fields SPECTRE reads inside sat1/sat2: {', '.join(NESTED_EXPECTED)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("satno", type=int, help="a NORAD catalogue number with known conjunctions, for example 25544")
    ap.add_argument("--mode", default="REAL", choices=("REAL", "TEST", "SIMULATED", "EXERCISE"))
    ap.add_argument("--max", type=int, default=5, help="records to read a side (default 5)")
    ap.add_argument("--base", default=DEFAULT_BASE)
    a = ap.parse_args()
    user = os.environ.get("UDL_USERNAME") or input("UDL username: ")
    password = os.environ.get("UDL_PASSWORD") or getpass.getpass("UDL password: ")
    auth = base64.b64encode(f"{user}:{password}".encode()).decode()
    print(f"SPC-033 probe: {a.base}{PATH}, catalogue number {a.satno}, dataMode {a.mode}, up to {a.max} a side")
    _report_query_help(a.base, auth)
    print("\n2. Records")
    seen: dict[str, set[str]] = {}
    for side in SIDES:
        params = {side: str(a.satno), "dataMode": a.mode, "maxResults": str(a.max)}
        status, payload, text = _get(a.base, PATH, params, auth)
        print(f"\n  {side}={a.satno}: HTTP {status}")
        if payload is None:
            print(f"  not JSON: {text!r}")
            continue
        _report_records(side, _records(payload)[: a.max], seen)
    _report_expected(seen)
    print("\nPaste everything above back into the SPECTRE session.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
