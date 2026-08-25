#!/bin/sh
# ---------------------------------------------------------------------------
# scripts/audit-dependencies.sh
#
# Everything we can prove locally about the dependency tree, in one run:
#
#   1. Vulnerability audit of requirements.txt (pip-audit, PyPI advisory data).
#   2. A CycloneDX Software Bill of Materials (SBOM), written to dist/.
#   3. The Python floor: the lowest interpreter version on which the pinned
#      manifest can actually be resolved.
#
# Step 3 exists because of a real deployment failure. The App Store's
# Dependency Scanning stage runs `pip download` against the manifest before it
# can analyse anything. If the analyser's interpreter is older than the floor,
# resolution fails, the job exits non-zero with no report artifact, and the
# platform surfaces that as "Vulnerable dependencies found" - a scan that never
# ran, reported as a finding. Knowing the floor turns that into a fact we can
# hand to the platform team.
#
# Requires network access to PyPI.
#
# Usage:  scripts/audit-dependencies.sh [output-dir]     (default: dist)
# ---------------------------------------------------------------------------

set -eu

OUT_DIR="${1:-dist}"
REQ="requirements.txt"
[ -f "$REQ" ] || { echo "FAIL: $REQ not found; run from the repository root"; exit 1; }
mkdir -p "$OUT_DIR"

VERSION=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' spectre/__init__.py)
SBOM="${OUT_DIR}/spectre-${VERSION}-sbom.cdx.json"

echo
echo "== 1. Vulnerability audit =="
if pip-audit --desc on --requirement "$REQ"; then
    echo "  PASS  no known vulnerabilities in $REQ"
else
    echo "  FAIL  pip-audit reported findings above"
    exit 1
fi

echo
echo "== 2. Software Bill of Materials =="
pip-audit --requirement "$REQ" --format cyclonedx-json --output "$SBOM" >/dev/null
COMPONENTS=$(python3 -c "import json,sys; print(len(json.load(open('$SBOM')).get('components',[])))")
echo "  wrote $SBOM ($COMPONENTS components)"

echo
echo "== 3. Python resolution floor =="
echo "  The manifest must resolve on whatever interpreter the scanner runs."
FLOOR=""
for PY in 3.9 3.10 3.11 3.12 3.13 3.14; do
    TMP=$(mktemp -d)
    if pip download -q --only-binary :all: --python-version "$PY" \
            -r "$REQ" -d "$TMP" >/dev/null 2>&1; then
        echo "  python $PY  RESOLVES"
        [ -n "$FLOOR" ] || FLOOR="$PY"
    else
        echo "  python $PY  cannot resolve"
    fi
    rm -rf "$TMP"
done

echo
if [ -n "$FLOOR" ]; then
    echo "  Resolution floor: python ${FLOOR}."
    echo "  A Dependency Scanning analyser older than ${FLOOR} CANNOT scan this"
    echo "  manifest. That is an analyser configuration matter, not a vulnerable"
    echo "  package: see docs/DEPENDENCY-SCANNING.md."
else
    echo "  FAIL  the manifest resolves on no tested interpreter"
    exit 1
fi
