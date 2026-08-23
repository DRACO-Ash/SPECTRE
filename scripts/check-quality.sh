#!/bin/sh
# SonarQube-equivalent quality check for changed code.
#
# The App Store quality gate scores NEW and CHANGED code only, on six
# conditions: zero new bugs, zero new vulnerabilities, zero new code smells,
# coverage at or above 80%, duplication at or below 3%, and every security
# hotspot reviewed. This script reproduces the first five locally, so violations
# are fixed one at a time instead of six hundred at once on upload.
#
# POSIX sh only: the platform runs steps under a minimal shell.
#
# Usage:  scripts/check-quality.sh [base-branch]      (default: master)

set -eu

BASE="${1:-master}"
COVERAGE_XML="coverage.xml"
COVERAGE_FLOOR=80
DUPLICATION_CEILING=3

# Scope mirrors sonar-project.properties, because that is what the platform
# analyses: sonar.sources (spectre, tle_clustering) and sonar.tests (tests).
# Anything else in the repository, scripts/ included, is not scanned by the
# gate, so scanning it here would invent failures the platform will never raise.
SOURCE_DIRS="spectre tle_clustering"
TEST_DIRS="tests"

# Rules approximating the SonarQube Python profile. Excluded, each with a reason:
#   E501    line length is governed by the formatter's 120-column setting
#   B008    FastAPI's Depends() in a default argument is the framework idiom
#   PTH123  open() versus Path.open() is a style preference, not a Sonar rule
#   TRY003, EM101, EM102  long, specific exception messages are deliberate: the
#           errno and the remedy in the message are the diagnostic feature
#   PLC0415 deferred imports are intentional (breaking a circular import in
#           deps.py, and importing after env setup in tests); SonarQube Python
#           has no equivalent rule
#   ARG     FastAPI route signatures carry parameters a handler may not use
RULES="F,E,W,B,SIM,C90,N,S,BLE,A,C4,DTZ,T20,PIE,RET,SLF,ERA,PL,TRY400,PERF,LOG,G,RUF100"
IGNORED="E501,B008,PTH123,TRY003,EM101,EM102,PLC0415,ARG"

# Test code additionally drops rules that describe how a suite is written, not a
# defect. Sonar applies a reduced profile to sonar.tests for the same reason.
#   S101    assert is the point of a test
#   S105/6  fixture credentials for an in-memory database
#   SLF001  a unit test may legitimately exercise a private function
#   PLR2004 a status code in an assertion IS the assertion
TEST_IGNORED="$IGNORED,S101,S105,S106,SLF001,PLR2004"

pass() { printf '  PASS  %s\n' "$1"; }
fail() { printf '  FAIL  %s\n' "$1"; exit 1; }

changed_in() {
    # $1 = space-separated directories
    # shellcheck disable=SC2086
    git diff --name-only "$BASE...HEAD" -- $1 2>/dev/null | while read -r f; do
        case "$f" in *.py) [ -f "$f" ] && printf '%s\n' "$f" ;; esac
    done
}

SRC_FILES=$(changed_in "$SOURCE_DIRS" | tr '\n' ' ')
TST_FILES=$(changed_in "$TEST_DIRS" | tr '\n' ' ')

if [ -z "$SRC_FILES" ] && [ -z "$TST_FILES" ]; then
    printf '\nNo analysed Python files changed against %s. Nothing to check.\n\n' "$BASE"
    exit 0
fi

printf '\n== Static analysis on changed LINES (bugs, vulnerabilities, smells) ==\n'
# Findings are filtered to lines this branch changed, matching the gate's
# new-code scope. A pre-existing smell in a touched file is not a new violation.
SCOPED_OK=0
if [ -n "$SRC_FILES" ]; then
    # shellcheck disable=SC2086
    ruff check --no-cache --isolated --line-length 120 --target-version py312 \
        --select "$RULES" --ignore "$IGNORED" --output-format=json --exit-zero $SRC_FILES \
        | python3 scripts/sonar_scope.py "$BASE" || SCOPED_OK=1
fi
if [ -n "$TST_FILES" ]; then
    # shellcheck disable=SC2086
    ruff check --no-cache --isolated --line-length 120 --target-version py312 \
        --select "$RULES" --ignore "$TEST_IGNORED" --output-format=json --exit-zero $TST_FILES \
        | python3 scripts/sonar_scope.py "$BASE" || SCOPED_OK=1
fi
[ "$SCOPED_OK" -eq 0 ] || fail "the findings above land on changed code and must be zero"
pass "no new bugs, vulnerabilities or code smells on changed lines"

printf '\n== Coverage on changed lines ==\n'
[ -f "$COVERAGE_XML" ] || fail "$COVERAGE_XML not found; run pytest --cov --cov-report=xml:$COVERAGE_XML first"
if diff-cover "$COVERAGE_XML" --compare-branch="$BASE" --fail-under="$COVERAGE_FLOOR" >/tmp/diffcov.out 2>&1; then
    pass "$(grep -E '^Coverage: ' /tmp/diffcov.out || echo "at or above ${COVERAGE_FLOOR}%")"
else
    cat /tmp/diffcov.out
    fail "coverage on changed lines is below ${COVERAGE_FLOOR}%"
fi

printf '\n== Duplication on changed files ==\n'
if command -v npx >/dev/null 2>&1; then
    SCAN=$(mktemp -d)
    { changed_in "$SOURCE_DIRS"; changed_in "$TEST_DIRS"; } | while read -r f; do
        mkdir -p "$SCAN/$(dirname "$f")"
        cp "$f" "$SCAN/$f"
    done
    # Thresholds match Sonar's Python defaults: 10 lines / 100 tokens minimum.
    npx --yes jscpd@4 "$SCAN" --min-lines 10 --min-tokens 100 \
        --formats-exts python:py --reporters console --silent \
        --threshold "$DUPLICATION_CEILING" >/tmp/jscpd.out 2>&1 && DUP_OK=0 || DUP_OK=1
    grep -E 'Found .* clones' /tmp/jscpd.out || true
    rm -rf "$SCAN"
    [ "$DUP_OK" -eq 0 ] || fail "duplication exceeds ${DUPLICATION_CEILING}%"
    pass "duplication at or below ${DUPLICATION_CEILING}%"
else
    fail "npx not available, so duplication could not be measured (this is 'could not check', not 'clean')"
fi

printf '\nAll quality-gate conditions reproduced locally are green.\n'
printf 'Security hotspots require a documented review; see READINESS.md.\n\n'
