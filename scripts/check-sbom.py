#!/usr/bin/env python3
"""Check that a CycloneDX SBOM lists every package a lock file pins.

CI writes the SBOM for requirements-runtime.txt, the lock the image installs
(SEC-04). An SBOM missing a package is worse than none, because it is read as
complete, so this exits 1 naming each pinned package the SBOM leaves out.

Usage:  scripts/check-sbom.py <sbom.cdx.json> <lock file>
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# A pin line: name, optional [extras], then ==version. Hash and comment lines
# never match, because they start with whitespace or '#'.
_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?==", re.MULTILINE)


def _normalise(name: str) -> str:
    """The PEP 503 form, so 'Alpha_Pkg' in a lock matches 'alpha-pkg' in an SBOM."""
    return re.sub(r"[-_.]+", "-", name).lower()


def missing_from_sbom(sbom_path: Path, lock_path: Path) -> list[str]:
    """Every package pinned in *lock_path* that *sbom_path* does not list."""
    document = json.loads(sbom_path.read_text(encoding="utf-8"))
    if document.get("bomFormat") != "CycloneDX":
        raise ValueError(f"{sbom_path} is not a CycloneDX document")
    listed = {_normalise(str(c.get("name", ""))) for c in document.get("components", [])}
    pinned = [_normalise(n) for n in _PIN.findall(lock_path.read_text(encoding="utf-8"))]
    return sorted(name for name in set(pinned) if name not in listed)


def main(argv: list[str]) -> int:
    if len(argv) != 3:  # noqa: PLR2004 - program name and two paths
        print(__doc__)
        return 2
    sbom, lock = Path(argv[1]), Path(argv[2])
    missing = missing_from_sbom(sbom, lock)
    if missing:
        print(f"FAIL  {sbom} omits {len(missing)} pinned package(s): {', '.join(missing)}")
        return 1
    count = len(json.loads(sbom.read_text(encoding="utf-8")).get("components", []))
    print(f"PASS  {sbom} lists all {count} packages pinned in {lock}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
