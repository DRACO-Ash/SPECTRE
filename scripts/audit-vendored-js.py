#!/usr/bin/env python3
"""Check the vendored JavaScript against the OSV vulnerability database.

pip-audit sees only the Python lock files, so the four libraries served from
spectre/web/static were never scanned (audit F-187). Their names and versions
are in spectre/web/static/vendored.json; this asks OSV about each and exits 1
if any has a known vulnerability.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

_MANIFEST = Path(__file__).resolve().parents[1] / "spectre" / "web" / "static" / "vendored.json"
_OSV = "https://api.osv.dev/v1/querybatch"


def main() -> int:
    packages = json.loads(_MANIFEST.read_text(encoding="utf-8"))["packages"]
    queries = [{"package": {"name": p["name"], "ecosystem": p["ecosystem"]}, "version": p["version"]} for p in packages]
    request = urllib.request.Request(  # noqa: S310 - fixed https URL
        _OSV, data=json.dumps({"queries": queries}).encode(), headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - fixed https URL
        results = json.loads(response.read())["results"]
    found = 0
    for package, result in zip(packages, results, strict=True):
        ids = [v["id"] for v in result.get("vulns", [])]
        status = ", ".join(ids) if ids else "no known vulnerabilities"
        print(f"{package['name']} {package['version']}: {status}")
        found += len(ids)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
