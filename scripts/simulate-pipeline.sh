#!/bin/sh
# Simulate the Bluestaq App Store pipeline against the ACTUAL upload artefact.
#
# A green repo loop is not a green upload. The platform copies your zip into a
# GitLab project it owns, ADDS ITS OWN .gitlab-ci.yml to that checkout, sets
# GITLAB_CI=true, and runs from there. This reproduces that: the artefact, the
# added file, the environment, and the build from the unzipped root as context.
#
# Run before every upload.
#
# POSIX sh only. Behind a TLS-terminating proxy, set PROXY_CA_BUNDLE so the
# image build can reach the package index (build-time only; see verify-container.sh).
#
# Usage:  scripts/simulate-pipeline.sh [zip-path]

set -eu

ZIP="${1:-}"
WORK=""
IMAGE="spectre:pipeline-sim"
CONTAINER="spectre-sim-$$"
HOST_PORT="${HOST_PORT:-18110}"

pass() { printf '  PASS  %s\n' "$1"; }
fail() { printf '  FAIL  %s\n' "$1"; exit 1; }

cleanup() {
    docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
    [ -n "$WORK" ] && rm -rf "$WORK"
    return 0
}
trap cleanup EXIT INT TERM

printf '\n== Stage 0: produce the artefact ==\n'
if [ -z "$ZIP" ]; then
    sh scripts/package-appstore.sh >/dev/null
    VERSION=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' spectre/__init__.py)
    ZIP="dist/spectre-${VERSION}-appstore.zip"
fi
[ -f "$ZIP" ] || fail "package not found: $ZIP"
pass "artefact: $ZIP"

printf '\n== Stage 1: checkout (unzip into a clean directory) ==\n'
WORK=$(mktemp -d)
unzip -q "$ZIP" -d "$WORK"
[ -f "$WORK/Dockerfile" ] || fail "no Dockerfile at the checkout root; template detection would fail"
pass "unzipped flat, Dockerfile at the checkout root"

# The platform commits its own CI file into the checkout. Any assertion in the
# suite about files that "must not exist" has to survive this.
printf 'stages:\n  - test\n' > "$WORK/.gitlab-ci.yml"
pass "platform .gitlab-ci.yml added to the checkout"

printf '\n== Stage 2: test the artefact in the platform environment ==\n'
# Reuses the developer virtualenv if present; the platform installs from the
# lockfile, which the image build exercises separately in stage 3.
if [ -x "$PWD/.venv/bin/python" ]; then
    PY="$PWD/.venv/bin/python"
else
    PY=python3
fi
( cd "$WORK" && GITLAB_CI=true SECRET_KEY=pipeline-sim-ephemeral-signing-key \
    "$PY" -m pytest tests/ -q --cov --cov-report=xml:coverage.xml >/tmp/sim-test.out 2>&1 ) \
    || { tail -30 /tmp/sim-test.out; fail "the suite is red on the artefact under GITLAB_CI=true"; }
tail -1 /tmp/sim-test.out
pass "suite green on the artefact with GITLAB_CI=true"

# A comprehensive suite that emits no machine-readable report scores 0% at the
# quality gate, so the artefact itself is checked, not just the exit code.
[ -s "$WORK/coverage.xml" ] || fail "coverage.xml is missing or empty; the gate would score 0%"
pass "coverage.xml produced and non-empty ($(wc -c < "$WORK/coverage.xml") bytes)"

printf '\n== Stage 3: containerize (build from the checkout root as context) ==\n'
BUILD_FILE="Dockerfile"
if [ -n "${PROXY_CA_BUNDLE:-}" ] && [ -f "$PROXY_CA_BUNDLE" ]; then
    cp "$PROXY_CA_BUNDLE" "$WORK/.sim-proxy-ca.crt"
    awk '
      /^COPY requirements\.lock \.\/$/ {
        print "COPY .sim-proxy-ca.crt /tmp/ca.crt"
        print "ENV PIP_CERT=/tmp/ca.crt"
      }
      { print }
    ' "$WORK/Dockerfile" > "$WORK/Dockerfile.sim"
    BUILD_FILE="Dockerfile.sim"
    printf '  note  proxy CA trusted for the build only\n'
fi
( cd "$WORK" && docker build --network host -f "$BUILD_FILE" -t "$IMAGE" . >/tmp/sim-build.out 2>&1 ) \
    || { tail -30 /tmp/sim-build.out; fail "image build from the artefact"; }
grep -E 'OS PATCH|SUID SWEEP' /tmp/sim-build.out | sed 's/^/  /' || true
pass "image builds from the unzipped root as context"

printf '\n== Stage 4: container scan equivalents ==\n'
uid=$(docker run --rm --entrypoint /opt/venv/bin/python "$IMAGE" -c 'import os;print(os.getuid())')
[ "$uid" != "0" ] || fail "runs as root"
pass "non-root uid $uid"

suid=$(docker run --rm --entrypoint /bin/sh "$IMAGE" -c \
    'find / -xdev -perm /6000 \( -type f -o -type d \) 2>/dev/null | wc -l')
[ "$suid" -eq 0 ] || fail "$suid setuid/setgid paths ship"
pass "no setuid or setgid paths"

for bin in pip apt apt-get dpkg; do
    docker run --rm --entrypoint /bin/sh "$IMAGE" -c "command -v $bin" >/dev/null 2>&1 \
        && fail "package manager ships: $bin"
done
pass "no package manager ships"

printf '\n== Stage 5: deploy (runtime contract) ==\n'
secret=$(docker run --rm --entrypoint /opt/venv/bin/python "$IMAGE" -c 'import secrets;print(secrets.token_urlsafe(32))')
docker run -d --name "$CONTAINER" -p "$HOST_PORT:8080" -e SECRET_KEY="$secret" \
    -e SPECTRE_ADMIN_USER=sim -e SPECTRE_ADMIN_PASS=sim-only-password "$IMAGE" >/dev/null
i=0
while [ "$i" -lt 60 ]; do
    curl -sf -o /dev/null "http://127.0.0.1:$HOST_PORT/healthz" 2>/dev/null && break
    i=$((i + 1)); sleep 1
done
[ "$i" -lt 60 ] || { docker logs "$CONTAINER"; fail "pod never became ready"; }
pass "boots and serves in ${i}s"

for path in "" healthz readyz; do
    code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$HOST_PORT/$path")
    [ "$code" = "200" ] || fail "GET /$path returned $code, must be 200"
    pass "GET /$path returns 200"
done

printf '\nPipeline simulation green. The artefact builds, tests and serves.\n'
printf 'Not reproduced locally (server-side): the SonarQube rule set and the\n'
printf 'image policy scan. See scripts/check-quality.sh and READINESS.md.\n\n'
