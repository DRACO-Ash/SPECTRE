#!/bin/sh
# The SonarQube gate: ZERO open issues and ZERO unreviewed security hotspots,
# across the whole package, measured by a real SonarQube at check time.
#
# Owner's instruction, 18 November 2026. It supersedes the ruling of 12
# November (latent issues converted as touched, new code only): the platform's
# SonarQube listed 165 code smells and 9 bugs on 0.48.5 while our own checker,
# which saw 14 rules on changed lines, passed it. A replica of the rules is not
# the analyser, so this runs the analyser. docs/CODE-QUALITY-GATE.md has the
# policy; scripts/sonar-profile.json is the rule set.
#
# POSIX sh, as the other scripts. The HTTP work is scripts/sonar_gate.py.
#
# Usage:
#   scripts/sonar-gate.sh [directory]
#     directory  the tree to analyse. Default: the App Store package tree,
#                staged by scripts/package-appstore.sh --stage-only, because
#                the platform analyses the uploaded archive and nothing else.
#
# Environment:
#   SONAR_HOST_URL     default http://127.0.0.1:9000. When nothing answers there
#                      and the host is local, the gate starts a SonarQube
#                      Community Build container on that port and removes it
#                      afterwards.
#   SONAR_AUTH_FILE    credentials for a server the gate did NOT start: a file
#                      holding user:password, a token, or the JSON a kept run
#                      leaves. The gate never prints what is in it.
#   SONAR_TOKEN        instead of SONAR_AUTH_FILE: a token able to create
#                      projects and quality profiles (CI secret, for example).
#   SONAR_PROJECT_KEY  default spectre-gate. Deleted and recreated every run.
#   SONAR_REPORT       the JSON report, default dist/sonar-gate-report.json
#   SONAR_CONTAINER    the container it starts, default spectre-sonar-gate
#   SONAR_KEEP=1       leave the container it started running, with its
#                      credentials in a private file whose PATH is printed
#   SONAR_START_TIMEOUT  seconds to wait for a started server, default 600
#   DOCKER             the docker executable, default docker
#
# Exit status: 0 pass; 1 issues or hotspots found; 2 the gate could not reach
# a verdict; 3 docker is not available. Anything but 0 stops a package build.

set -eu

ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
HELPER="$ROOT/scripts/sonar_gate.py"
PROFILE="$ROOT/scripts/sonar-profile.json"
PY="${PYTHON:-python3}"
DOCKER="${DOCKER:-docker}"

# Pinned by digest, so the gate is the same analyser on every machine and in CI.
#   sonarqube:community             SonarQube Community Build 26.11.0.134175
#   sonarsource/sonar-scanner-cli   SonarScanner CLI 8.4.0.16527
SONARQUBE_IMAGE="sonarqube@sha256:65541accbdb92e27fe770fc6ba99988a3dd5a0c71ffafd67f88abfad366996fa"
SCANNER_IMAGE="sonarsource/sonar-scanner-cli@sha256:6e6eca4d552695a98fb7dab84f0c1bd0885ebbfe272654d1552e24bd7f452d51"

HOST="${SONAR_HOST_URL:-http://127.0.0.1:9000}"
HOST="${HOST%/}"
PROJECT="${SONAR_PROJECT_KEY:-spectre-gate}"
CONTAINER="${SONAR_CONTAINER:-spectre-sonar-gate}"
REPORT="${SONAR_REPORT:-$ROOT/dist/sonar-gate-report.json}"

say() { printf '  %s\n' "$*"; }
refuse() { code=$1; shift; printf '  FAIL: %s\n' "$*" >&2; exit "$code"; }

# ── Docker is not optional ────────────────────────────────────────────────────
# The analyser and the scanner both run in containers. No docker means no
# verdict, and no verdict is a failure, never a pass.
if ! command -v "$DOCKER" >/dev/null 2>&1 || ! "$DOCKER" info >/dev/null 2>&1; then
    refuse 3 "docker is not available ($DOCKER), so the SonarQube gate cannot run.
        Install or start docker and run again. There is no fallback that counts as a pass."
fi
command -v "$PY" >/dev/null 2>&1 || refuse 2 "$PY is not available"

# Private scratch: the credentials file is created 0600 inside a 0700 folder.
umask 077
WORK=$(mktemp -d)
SECRETS="$WORK/credentials.json"
: > "$SECRETS"
STARTED=""

cleanup() {
    status=$?
    trap - EXIT INT TERM
    if [ -s "$SECRETS" ] && [ -z "$STARTED" ]; then
        "$PY" "$HELPER" revoke --host "$HOST" --secrets "$SECRETS" >/dev/null 2>&1 || true
    fi
    if [ -n "$STARTED" ] && [ "${SONAR_KEEP:-0}" = "1" ]; then
        KEPT=$(mktemp)
        cp "$SECRETS" "$KEPT"
        say "SONAR_KEEP=1: container $CONTAINER left running at $HOST"
        say "its credentials are in $KEPT (mode 0600); delete the file when done, and"
        say "pass it as SONAR_AUTH_FILE to reuse the server"
    elif [ -n "$STARTED" ]; then
        "$DOCKER" rm -f -v "$CONTAINER" >/dev/null 2>&1 || true
    fi
    rm -rf "$WORK"
    exit "$status"
}
trap cleanup EXIT
trap 'exit 2' INT TERM

# ── What to analyse ───────────────────────────────────────────────────────────
if [ "$#" -ge 1 ]; then
    [ -d "$1" ] || refuse 2 "$1 is not a directory"
    TARGET=$(cd -- "$1" && pwd)
else
    TARGET="$WORK/package"
    say "staging the App Store package tree (scripts/package-appstore.sh --stage-only)"
    (cd "$ROOT" && sh scripts/package-appstore.sh --stage-only "$TARGET") >"$WORK/stage.log" 2>&1 \
        || { cat "$WORK/stage.log"; refuse 2 "the package tree could not be staged"; }
fi
"$PY" -c 'import json,sys; json.load(open(sys.argv[1]))' "$PROFILE" 2>/dev/null \
    || refuse 2 "$PROFILE is missing or is not JSON"

# ── A server: reuse one that answers, or start a fresh one ───────────────────
if "$PY" "$HELPER" wait-up --host "$HOST" --once >/dev/null 2>&1; then
    say "using the SonarQube already running at $HOST"
    if [ -z "${SONAR_AUTH_FILE:-}" ] && [ -n "${SONAR_TOKEN:-}" ]; then
        SONAR_AUTH_FILE="$WORK/given-token"
        printf '%s\n' "$SONAR_TOKEN" > "$SONAR_AUTH_FILE"
    fi
    [ -n "${SONAR_AUTH_FILE:-}" ] && [ -r "${SONAR_AUTH_FILE}" ] || refuse 2 "a SonarQube answers at $HOST but no credentials were given.
        Set SONAR_AUTH_FILE (user:password or a token, in a file) or SONAR_TOKEN,
        or point SONAR_HOST_URL at a free local port so the gate starts its own."
    "$PY" "$HELPER" bootstrap --host "$HOST" --secrets "$SECRETS" --auth-file "$SONAR_AUTH_FILE" \
        || refuse 2 "the credentials were refused by $HOST"
    SET_DEFAULT=""
else
    case "$HOST" in
        http://127.0.0.1:*|http://localhost:*) ;;
        *) refuse 2 "nothing answers at $HOST, and the gate starts a server only on a local port" ;;
    esac
    PORT="${HOST##*:}"
    case "$PORT" in ''|*[!0-9]*) refuse 2 "SONAR_HOST_URL must name a port, for example http://127.0.0.1:9000" ;; esac
    if "$DOCKER" container inspect "$CONTAINER" >/dev/null 2>&1; then
        refuse 2 "a container named $CONTAINER exists but nothing answers at $HOST.
        Remove it (docker rm -f -v $CONTAINER) or set SONAR_CONTAINER."
    fi
    say "starting SonarQube Community Build in container $CONTAINER on port $PORT"
    # Data on tmpfs: Elasticsearch refuses a disk under 10% free, and nothing
    # here should outlive the run. Bootstrap checks off: they test the host's
    # kernel settings for a production cluster, not this throwaway server.
    "$DOCKER" run -d --name "$CONTAINER" -p "127.0.0.1:$PORT:9000" \
        --tmpfs /opt/sonarqube/data:size=6g,uid=1000,gid=0,mode=0775 \
        -e SONAR_ES_BOOTSTRAP_CHECKS_DISABLE=true -e SONAR_TELEMETRY_ENABLE=false \
        "$SONARQUBE_IMAGE" >/dev/null || refuse 2 "the SonarQube container did not start"
    STARTED=1
    if ! "$PY" "$HELPER" wait-up --host "$HOST" --timeout "${SONAR_START_TIMEOUT:-600}"; then
        "$DOCKER" logs --tail 40 "$CONTAINER" 2>&1 | sed 's/^/    /'
        refuse 2 "SonarQube did not come up"
    fi
    say "SonarQube is UP; setting a random admin password and minting a token"
    "$PY" "$HELPER" bootstrap --host "$HOST" --secrets "$SECRETS" --fresh \
        || refuse 2 "could not secure the fresh server"
    SET_DEFAULT="--set-default"
fi

# ── The quality profile and a fresh project ──────────────────────────────────
say "building the quality profile from scripts/sonar-profile.json"
# shellcheck disable=SC2086
"$PY" "$HELPER" prepare --host "$HOST" --secrets "$SECRETS" --profile "$PROFILE" \
    --project "$PROJECT" $SET_DEFAULT || refuse 2 "the quality profile or the project could not be set up"

# ── Scan: the whole tree, as the platform does ───────────────────────────────
# The platform's Code Quality stage analyses every file in the archive and does
# not honour sonar.sources, so the scope here is the whole tree: sources are
# everything, tests/ is analysed as test code. These settings override any
# sonar-project.properties in the tree, so the package cannot narrow its own
# analysis. A scan of 0.48.5 this way reported exactly the 206 issues of the
# reference scan, file for file and line for line.
mkdir -p "$WORK/scan"
TOKEN=$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["token"])' "$SECRETS")
if [ -d "$TARGET/tests" ]; then
    set -- -Dsonar.tests=tests -Dsonar.exclusions='tests/**'
else
    set --
fi
say "analysing $TARGET"
if ! SONAR_TOKEN="$TOKEN" "$DOCKER" run --rm --network host --user "$(id -u):$(id -g)" \
        -e SONAR_HOST_URL="$HOST" -e SONAR_TOKEN -e SONAR_USER_HOME=/work/.sonar \
        -v "$TARGET:/usr/src:ro" -v "$WORK/scan:/work" \
        "$SCANNER_IMAGE" \
        -Dsonar.projectKey="$PROJECT" -Dsonar.projectName="SPECTRE gate" \
        -Dsonar.working.directory=/work/scannerwork -Dsonar.scm.disabled=true \
        -Dsonar.sources=. -Dsonar.sourceEncoding=UTF-8 -Dsonar.python.version=3.12 \
        "$@" >"$WORK/scanner.log" 2>&1; then
    tail -25 "$WORK/scanner.log" | sed 's/^/    /'
    grep -E 'ERROR|Caused by' "$WORK/scanner.log" | tail -15 | sed 's/^/    /' || true
    # A scan that ends on "EXECUTION FAILURE" with no ERROR line was killed
    # from outside: on a busy machine, the kernel's out-of-memory killer.
    refuse 2 "the scanner failed (no verdict). If no ERROR line shows above, it was probably
        killed for memory: the scanner wants about 3 GB and the server about 4 GB."
fi
TOKEN=""
grep -E 'languages detected|source files to be analyzed' "$WORK/scanner.log" | sed 's/^[0-9:.]* INFO  /    /' || true

"$PY" "$HELPER" wait-task --host "$HOST" --secrets "$SECRETS" \
    --report-task "$WORK/scan/scannerwork/report-task.txt" || refuse 2 "the analysis was not processed"

# ── The verdict ──────────────────────────────────────────────────────────────
mkdir -p "$(dirname -- "$REPORT")"
set +e
"$PY" "$HELPER" report --host "$HOST" --secrets "$SECRETS" --project "$PROJECT" \
    --out "$REPORT" --profile "$PROFILE" --target "$TARGET"
VERDICT=$?
set -e
say "report: $REPORT"
case "$VERDICT" in
    0) say "PASS: SonarQube reports zero open issues and zero security hotspots to review" ;;
    1) printf '  FAIL: SonarQube reports the issues above. The gate is zero, across the whole package.\n' >&2 ;;
    *) refuse 2 "the issues could not be read" ;;
esac
exit "$VERDICT"
