#!/bin/sh
# ---------------------------------------------------------------------------
# scripts/verify-dependency-scan.sh
#
# Run the App Store's actual Dependency Scanning analyser against a built
# package, locally, before submitting.
#
# The platform reports this stage as "Vulnerable dependencies found" whenever
# the analyser exits non-zero, including when it crashed and found nothing at
# all. The job log is often unavailable and the analyser's own fatal message
# never reaches the interface. Four submissions were spent guessing at it. The
# analyser is open source, so run it here and read the real error.
#
# The analyser is built from
#   gitlab.com/gitlab-org/security-products/analyzers/dependency-scanning
# which is the upstream of the platform's dependency-scan-python image.
# Requires Go and network access on first run; the binary is then cached.
#
# Usage:
#   scripts/verify-dependency-scan.sh dist/spectre-0.4.6-appstore.zip
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
        echo "  PASS  analyser exited 0 and wrote $SBOMS SBOM(s), $COMPONENTS components"
    else
        # Correct and expected for docker-only, which ships no manifest.
        echo "  PASS  analyser exited 0 with no manifest to scan"
        grep -oE "No compatible file found[^\"]*" "$WORK/ds.log" | head -1 | sed 's/^/        /'
    fi
else
    echo "  FAIL  the analyser exited non-zero. The platform will report this as"
    echo "        \"Vulnerable dependencies found\". Its real complaint:"
    echo
    grep -E "FATA|ERRO|parsing error" "$WORK/ds.log" | sed 's/^/    /'
    exit 1
fi
