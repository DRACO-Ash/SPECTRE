#!/bin/sh
# ---------------------------------------------------------------------------
# scripts/bump-version.sh
#
# Iterate the SPECTRE version. Every App Store submission carries a distinct
# version so the platform, the pipeline log and the artefact on disk can never
# disagree about which build is which.
#
# The version is single-sourced in spectre/__init__.py; hatch reads it from
# there for pyproject, and the packager reads it for the zip name. This script
# updates that one line, then rewrites the documentation references that quote
# the version literally so they cannot drift.
#
# Usage:
#   scripts/bump-version.sh patch     0.4.0 -> 0.4.1   (default)
#   scripts/bump-version.sh minor     0.4.0 -> 0.5.0
#   scripts/bump-version.sh major     0.4.0 -> 1.0.0
#   scripts/bump-version.sh 0.9.3     set explicitly
#
# It does not commit, tag or push. Review the diff, add the CHANGELOG entry,
# then commit.
# ---------------------------------------------------------------------------

set -eu

INIT="spectre/__init__.py"
CURRENT=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "$INIT")
[ -n "$CURRENT" ] || { echo "FAIL: could not read __version__ from $INIT"; exit 1; }

case "$CURRENT" in
    [0-9]*.[0-9]*.[0-9]*) ;;
    *) echo "FAIL: current version '$CURRENT' is not MAJOR.MINOR.PATCH"; exit 1 ;;
esac

MAJOR=${CURRENT%%.*}
REST=${CURRENT#*.}
MINOR=${REST%%.*}
PATCH=${REST#*.}

case "${1:-patch}" in
    patch) NEXT="${MAJOR}.${MINOR}.$((PATCH + 1))" ;;
    minor) NEXT="${MAJOR}.$((MINOR + 1)).0" ;;
    major) NEXT="$((MAJOR + 1)).0.0" ;;
    [0-9]*.[0-9]*.[0-9]*) NEXT="$1" ;;
    *) echo "FAIL: expected patch, minor, major or an explicit MAJOR.MINOR.PATCH; got '$1'"; exit 1 ;;
esac

[ "$NEXT" != "$CURRENT" ] || { echo "FAIL: $NEXT is already the current version"; exit 1; }

# The single source of truth.
sed -i "s/^__version__ = \"${CURRENT}\"$/__version__ = \"${NEXT}\"/" "$INIT"

# pyproject.toml carries the version literally now: the App Store gate contract
# wants a [project] table, and dropping hatch's dynamic version with it. This is
# the only place it is rewritten, so it can never drift from spectre/__init__.py.
sed -i "s/^version = \"${CURRENT}\"$/version = \"${NEXT}\"/" pyproject.toml
PYPROJECT_VERSION=$(sed -n 's/^version = "\(.*\)"$/\1/p' pyproject.toml)
[ "$PYPROJECT_VERSION" = "$NEXT" ] || {
    echo "FAIL: pyproject.toml still reads '${PYPROJECT_VERSION}', expected ${NEXT}"; exit 1; }

# Documentation quotes the version as literal text, so rewrite those too. Only
# whole-version matches are replaced, guarded by a word boundary either side.
DOCS="READINESS.md README.md"
for doc in $DOCS; do
    [ -f "$doc" ] || continue
    sed -i "s/\b${CURRENT}\b/${NEXT}/g" "$doc"
done

CONFIRM=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "$INIT")
[ "$CONFIRM" = "$NEXT" ] || { echo "FAIL: rewrite did not take (still $CONFIRM)"; exit 1; }

echo "  version   ${CURRENT} -> ${NEXT}"
echo
echo "Next:"
echo "  1. add a CHANGELOG.md entry under ## [${NEXT}]"
echo "  2. run the loop:  scripts/check-quality.sh"
echo "  3. repackage:     scripts/package-appstore.sh"
