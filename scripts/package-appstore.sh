#!/bin/sh
# Build the Bluestaq App Store upload package for SPECTRE.
#
# The package is a FLAT, TESTABLE SOURCE TREE:
#   * flat        the Dockerfile sits at the zip root, with no wrapping folder,
#                 so template detection finds it and the generated build uses
#                 the root as its context. A nested Dockerfile fails with
#                 "context must be a directory".
#   * testable    tests, their config and the lockfile all ship, so the platform
#                 can run the suite against the zip root. Under docker-only it
#                 will not, but a stripped runtime bundle cannot be reviewed and
#                 could not switch to the python template later.
#
# The packaging allowlist and .dockerignore are SEPARATE contracts: this shapes
# the upload the platform inspects, .dockerignore shapes the image it runs.
#
# POSIX sh only: the platform runs build steps under a minimal shell.
#
# Usage:
#   scripts/package-appstore.sh [output-dir]                  python template
#   scripts/package-appstore.sh [--docker-only] [output-dir]   flag order is free
#
# TEMPLATE SELECTION IS DECIDED BY WHAT IS IN THE PACKAGE, NOT BY A SETTING.
# The platform detects Python from a recognised manifest at the package root.
# Evidence: the first upload had pyproject.toml and no requirements.txt, and a
# Dependencies stage still ran and failed; a docker-only app has no such stage.
# So docker-only requires that NO recognised manifest ships: no pyproject.toml
# and no requirements.txt. requirements.lock is not a recognised name, so
# dependency pinning survives, and Dockerfile.docker-only runs the app via
# `python -m` instead of installing it.

set -eu

# Positional output dir and the --docker-only flag may appear in either order,
# so a bare `--docker-only` is not mistaken for a directory name.
OUT_DIR=""
MODE="python"
while [ "$#" -gt 0 ]; do
    case "$1" in
        --docker-only) MODE="docker-only" ;;
        -*) echo "FAIL: unknown option $1"; exit 1 ;;
        *)
            [ -z "$OUT_DIR" ] || { echo "FAIL: output dir given twice ($OUT_DIR, $1)"; exit 1; }
            OUT_DIR="$1"
            ;;
    esac
    shift
done
[ -n "$OUT_DIR" ] || OUT_DIR="dist"
VERSION=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' spectre/__init__.py)
[ -n "$VERSION" ] || { echo "FAIL: could not read __version__ from spectre/__init__.py"; exit 1; }

STAGE=$(mktemp -d)
if [ "$MODE" = "docker-only" ]; then
    PKG_NAME="spectre-${VERSION}-appstore-docker-only"
else
    PKG_NAME="spectre-${VERSION}-appstore"
fi
ZIP_PATH="${OUT_DIR}/${PKG_NAME}.zip"

cleanup() { rm -rf "$STAGE"; }
trap cleanup EXIT INT TERM

echo "Packaging SPECTRE ${VERSION} for the App Store (${MODE} template)"

# ── Allowlist ─────────────────────────────────────────────────────────────────
# Everything the platform needs to detect the template, build the image, run the
# suite, and review the submission. Nothing else.
PATHS="
Dockerfile
.dockerignore
pyproject.toml
requirements.in
requirements.txt
requirements-runtime.in
requirements-runtime.txt
pytest.ini
.coveragerc
sonar-project.properties
README.md
CHANGELOG.md
SECURITY.md
READINESS.md
CODEOWNERS
.env.example
.gitignore
.pre-commit-config.yaml
spectre
tests
tle_clustering
scripts
.github
"

if [ "$MODE" = "docker-only" ]; then
    # A recognised manifest anywhere at the root would flip the template back to
    # python, so requirements.txt and the Sonar config go. tests/ goes with
    # them, along with pytest.ini and .coveragerc: docker-only has no Test
    # stage, so shipping a suite and its configuration would only add files a
    # reviewer must account for.
    DROP="pyproject.toml requirements.in requirements.txt sonar-project.properties
tests tle_clustering .github .pre-commit-config.yaml .coveragerc"
    DROP="$DROP pytest.ini"
    KEPT=""
    for p in $PATHS; do
        skip=0
        for d in $DROP; do [ "$p" = "$d" ] && skip=1; done
        [ "$skip" = "1" ] || KEPT="$KEPT
$p"
    done
    PATHS="$KEPT"
fi

for p in $PATHS; do
    [ -e "$p" ] || { echo "FAIL: allowlisted path missing: $p"; exit 1; }
    mkdir -p "$STAGE/$(dirname "$p")"
    cp -R "$p" "$STAGE/$(dirname "$p")/"
done

# pyproject.toml SHIPS, and must. The Dependency Scanning analyser treats a
# non-Poetry pyproject.toml as a resolution trigger, and it is the only root
# file present in both applications known to clear the gate and absent from the
# one that failed. It carries a [project] table and no [project.dependencies];
# a build-system-only file is skipped with a warning and buys nothing.
#
# requirements-runtime.txt is not a filename the analyser recognises, so the
# gate never reads it. That is why it must stay a strict, version-identical
# subset of requirements.txt: otherwise the image would ship a version no stage
# examined. scripts/check-quality.sh asserts the subset.

# ── Denylist ──────────────────────────────────────────────────────────────────
# Removed after the copy so a nested match cannot survive. Each has a reason.
#   __pycache__, *.pyc      build cruft
#   .env and variants       real secrets must never travel in an upload
#   coverage output, .db    generated locally, regenerated by the pipeline
#   data/, logs/            runtime state; the container uses the storage add-on
#   dist/, *.zip            no package inside a package
#   docs/                   document generators and reference material. Not
#                           imported by the app, not needed to build or test,
#                           and its .py generators are analysed by the platform
#                           scanner as if they were application code, which
#                           lowers the coverage ratio and raises smells against
#                           files that never ship
find "$STAGE" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$STAGE" \( -name '*.pyc' -o -name '*.pyo' -o -name '*.db' -o -name '*.zip' \) -delete 2>/dev/null || true
find "$STAGE" \( -name '.env' -o -name '.env.*' \) ! -name '.env.example' -delete 2>/dev/null || true
find "$STAGE" \( -name '.coverage' -o -name 'coverage.xml' \) -delete 2>/dev/null || true
rm -rf "$STAGE/docs" "$STAGE/.git" "$STAGE/.venv" "$STAGE/venv" "$STAGE/dist" "$STAGE/htmlcov" \
       "$STAGE/coverage" "$STAGE/.pytest_cache" "$STAGE/.mypy_cache" "$STAGE/.ruff_cache" \
       "$STAGE/data" "$STAGE/logs" "$STAGE/docs/openapi.json"

if [ "$MODE" = "docker-only" ]; then
    [ -f Dockerfile.docker-only ] || { echo "FAIL: Dockerfile.docker-only is missing"; exit 1; }
    cp Dockerfile.docker-only "$STAGE/Dockerfile"
fi

# ── Fail-closed checks on the staged tree ─────────────────────────────────────
[ -f "$STAGE/Dockerfile" ] || { echo "FAIL: Dockerfile must be at the package root"; exit 1; }

if [ "$MODE" = "python" ]; then
    # The Dependencies stage installs from requirements.txt. Without it the
    # stage fails before anything else runs.
    if [ ! -f "$STAGE/requirements.txt" ]; then
        echo "FAIL: no requirements.txt at the package root."
        echo "      The platform's dependency install has nothing to read and will fail."
        exit 1
    fi
else
    # Any recognised manifest would flip detection back to the python template.
    for manifest in pyproject.toml requirements.txt setup.py setup.cfg Pipfile poetry.lock; do
        if [ -f "$STAGE/$manifest" ]; then
            echo "FAIL: $manifest at the root would select the python template, not docker-only."
            exit 1
        fi
    done
fi

LEAKS=$(find "$STAGE" \( -name '.env' -o -name '*.pem' -o -name '*.key' -o -name 'id_rsa*' \) 2>/dev/null | grep -v '\.env\.example' || true)
[ -z "$LEAKS" ] || { echo "FAIL: credential-shaped files in the package:"; echo "$LEAKS"; exit 1; }

if grep -rIlE '^SECRET_KEY=.+|^SPECTRE_ADMIN_PASS=.+' "$STAGE" 2>/dev/null | head -1 | grep -q .; then
    echo "FAIL: a populated secret value is present in the package"
    exit 1
fi

# ── Build ─────────────────────────────────────────────────────────────────────
mkdir -p "$OUT_DIR"
rm -f "$ZIP_PATH"
# -X drops extra file attributes so the archive is reproducible across machines.
# Resolve to an absolute path before the subshell changes directory, so an
# absolute output directory is not concatenated onto the current one.
ABS_ZIP=$(cd "$(dirname "$ZIP_PATH")" && pwd)/$(basename "$ZIP_PATH")
( cd "$STAGE" && zip -q -r -X "$ABS_ZIP" . )

# ── Integrity record ──────────────────────────────────────────────────────────
SHA=$(sha256sum "$ZIP_PATH" | cut -d' ' -f1)
SIZE=$(du -h "$ZIP_PATH" | cut -f1)
COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")

cat > "${OUT_DIR}/${PKG_NAME}.sha256" <<EOF
$SHA  ${PKG_NAME}.zip
EOF

echo
echo "  package   $ZIP_PATH"
echo "  version   $VERSION"
echo "  commit    $COMMIT"
echo "  size      $SIZE"
echo "  sha256    $SHA"
echo "  files     $(unzip -l "$ZIP_PATH" | tail -1 | awk '{print $2}')"
echo
# ── Post-build: run the suite from inside the package ─────────────────────────
# The platform runs `pip install -r requirements.txt && pytest` against the
# uploaded tree, not against this working copy. A test that passes here and
# fails there costs a whole submission cycle - it has already cost one, when a
# contract test asserted the presence of docs/, which the denylist above
# deliberately strips. Run the suite where the platform will run it.
if [ "$MODE" = "python" ] && [ "${SKIP_PACKAGE_TESTS:-0}" != "1" ]; then
    echo
    echo "  running the suite from inside the package..."
    VERIFY=$(mktemp -d)
    trap 'rm -rf "$STAGE" "$VERIFY"' EXIT INT TERM
    unzip -q "$ZIP_PATH" -d "$VERIFY"
    if (cd "$VERIFY" && SPECTRE_SECRET_KEY="package-verification-key-not-a-secret" \
            python -m pytest -q > "$VERIFY/suite.log" 2>&1); then
        echo "  suite passes inside the package"
    else
        echo "  FAIL: the suite does not pass inside the package."
        echo "  The platform Test stage will fail the same way. Tail of the run:"
        tail -25 "$VERIFY/suite.log" > "$VERIFY/tail.txt"
        sed 's/^/    /' "$VERIFY/tail.txt"
        exit 1
    fi
fi

# ── Post-build: gate pre-flight, then the diagnostic analyser ─────────────────
# preflight-gate.py is the check that decides whether to ship: it encodes the
# package contract derived from applications that actually clear the gate.
# verify-dependency-scan.sh is advisory only and cannot fail the build, because
# the open-source analyser disagreed with the gate on two of three known
# samples. Its header carries that calibration table.
# python mode only: the contract it checks (pyproject.toml, a scannable
# requirements.txt, a tests/ directory) is the python template's contract.
# docker-only deliberately ships none of them, so running it there would report
# the absences it is designed to cause.
if [ "$MODE" = "python" ] && [ -f scripts/preflight-gate.py ]; then
    echo
    python3 scripts/preflight-gate.py "$STAGE" || exit 1
fi
if [ "${SKIP_DS_VERIFY:-0}" != "1" ] && [ -x scripts/verify-dependency-scan.sh ]; then
    echo
    sh scripts/verify-dependency-scan.sh "$ZIP_PATH" || true
fi

echo "Verify the contents with:  unzip -l $ZIP_PATH"
