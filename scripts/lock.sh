#!/bin/sh
# Regenerate all three lock files, hash-locked, for one interpreter version.
#
# Never edit a .txt lock file by hand. The hashes are what make
# `pip install --require-hashes --no-deps` meaningful, and a hand-edited pin
# with a stale hash fails the container build rather than installing something
# unexpected. That is the correct behaviour and an expensive way to find a typo.
#
# --python-version is not optional, and the value is 3.11 for a specific
# reason that cost twelve submissions to find.
#
# The App Store's Dependency Scanning analyser is GitLab's gemnasium-python.
# Its image is built FROM python:3.11-slim (build/gemnasium-python/debian/
# Dockerfile, ARG DS_PYTHON_VERSION=3.11), and before it can analyse anything
# it runs, on that interpreter:
#
#     pip download --disable-pip-version-check --dest ./dist -r requirements.txt
#
# A manifest pinning any package that declares Requires-Python >= 3.12 cannot
# resolve there. pip exits non-zero, the analyser logs pip's output at DEBUG
# only, and the job dies in about three seconds with no error text, no SBOM and
# no report, which the interface renders as "Vulnerable dependencies found".
#
# So the lock is compiled for 3.11, the SCANNER's interpreter, while the app
# still runs on 3.12: a set resolved for 3.11 installs cleanly on 3.12, and
# --generate-hashes carries every wheel's hash, the cp312 ones included.
#
# scripts/audit-dependencies.sh measures the real floor and fails above 3.11.
#
# Usage:  sh scripts/lock.sh [PYTHON_VERSION]
#         sh scripts/lock.sh 3.11

set -eu

PYVER="${1:-3.11}"

if ! command -v uv >/dev/null 2>&1; then
    echo "error: uv not found." >&2
    echo "       Install it, or substitute: pip-compile --generate-hashes" >&2
    exit 2
fi

lock() {
    src="$1"
    dst="$2"
    if [ ! -f "$src" ]; then
        echo "skip: $src not present"
        return 0
    fi
    echo "lock: $src -> $dst"
    # Redirected, never piped: a pipeline reports the last command's status.
    uv pip compile --python-version "$PYVER" --generate-hashes "$src" -o "$dst"
}

lock requirements-runtime.in requirements-runtime.txt
lock requirements.in         requirements.txt
lock requirements-dev.in     requirements-dev.txt

echo
echo "Locked for Python ${PYVER}."
echo "Next: install the new pins, then run the loop. Leg one catches a lock"
echo "file that was regenerated but not installed, which is the usual next"
echo "mistake. Commit all three .txt files together."
echo
echo "Optional, and worth it once a week rather than on every change:"
echo "  uv pip compile --exclude-newer \$(date -d '7 days ago' +%Y-%m-%d) ..."
echo "  Delayed ingestion lets the wider community be the canary. It is one"
echo "  layer, not a guarantee, and it delays security patches, so keep an"
echo "  expedite path for a real fix."
