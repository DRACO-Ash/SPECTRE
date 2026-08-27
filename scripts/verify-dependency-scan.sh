#!/bin/sh
# ---------------------------------------------------------------------------
# scripts/verify-dependency-scan.sh
#
# DIAGNOSTIC ONLY. This is NOT a pre-flight check for the App Store gate.
#
# It builds the open-source GitLab analyser and runs it against a package. That
# analyser is not the one the platform runs, and calibrated against the three
# known control samples it disagreed with the gate on two of them:
#
#     Package               App Store gate     this script
#     PSIRENS 1.5.3         passed             exit 1, no SBOM
#     Enlightenment 0.23.3  passed             exit 0, 27 components
#     Legion 0.4.3          FAILED             exit 0, 57 components
#
# So a pass here is not evidence you will clear the gate, and a failure here is
# not a reason to change your package. The platform's analyser prints a line
# that exists nowhere in this codebase; it is a different tool.
#
# What it IS good for: reading the parse warnings the platform swallows. Run it
# to understand a package, never to decide whether to upload one. Use
# scripts/preflight-gate.py for that.
#
# Usage:
#   scripts/verify-dependency-scan.sh dist/spectre-0.5.0-appstore.zip
#
# Environment:
#   DS_ANALYZER_BIN   path to a prebuilt analyser binary, skipping the build
#   DS_CACHE_DIR      where to clone and cache (default: .cache/ds-analyzer)
# ---------------------------------------------------------------------------

set -eu

ZIP="${1:-}"
[ -n "$ZIP" ] && [ -f "$ZIP" ] || { echo "usage: $0 <package.zip>"; exit 1; }

CACHE="${DS_CACHE_DIR:-.cache/ds-analyzer}"
BIN="${DS_ANALYZER_BIN:-$CACHE/analyzer}"
REPO="https://gitlab.com/gitlab-org/security-products/analyzers/dependency-scanning.git"

if [ ! -x "$BIN" ]; then
    command -v go >/dev/null 2>&1 || {
        echo "SKIP: no Go toolchain, cannot build the analyser."
        echo "      Set DS_ANALYZER_BIN to a prebuilt binary to run this check."
        exit 0
    }
    echo "  building the analyser (first run only)..."
    mkdir -p "$CACHE"
    [ -d "$CACHE/src/.git" ] || git clone --depth 1 --quiet "$REPO" "$CACHE/src"
    ( cd "$CACHE/src" && go build -o ../analyzer ./cmd/dependency-scanning )
    BIN="$CACHE/analyzer"
fi

# Resolve to an absolute path: the analyser runs with the unpacked package as
# its working directory, so a relative path would no longer point at it.
BIN=$(cd "$(dirname "$BIN")" && pwd)/$(basename "$BIN")

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM
unzip -q "$ZIP" -d "$WORK"

echo "  running the analyser against $ZIP"
# GITLAB_FEATURES gates the analyser the same way the platform licence does.
if (cd "$WORK" && GITLAB_FEATURES=dependency_scanning "$BIN" run > "$WORK/ds.log" 2>&1); then
    SBOMS=$(find "$WORK" -maxdepth 1 -name 'gl-sbom-*.cdx.json' | wc -l)
    if [ "$SBOMS" -gt 0 ]; then
        COMPONENTS=$(python3 -c "
import glob,json
print(sum(len(json.load(open(f)).get('components',[])) for f in glob.glob('$WORK/gl-sbom-*.cdx.json')))")
        echo "  NOTE  analyser exited 0 and wrote $SBOMS SBOM(s), $COMPONENTS components"
    else
        # Correct and expected for docker-only, which ships no manifest.
        echo "  NOTE  analyser exited 0 with no manifest to scan"
        grep -oE "No compatible file found[^\"]*" "$WORK/ds.log" | head -1 | sed 's/^/        /'
    fi
else
    echo "  NOTE  the open-source analyser exited non-zero. This does NOT predict"
    echo "        the gate: it was wrong on two of three known samples. Its output,"
    echo "        which is still worth reading:"
    echo
    grep -E "FATA|ERRO|parsing error" "$WORK/ds.log" | sed 's/^/    /'
    exit 0
fi
