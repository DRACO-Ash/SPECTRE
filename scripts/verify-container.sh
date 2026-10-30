#!/bin/sh
# Verify the SPECTRE container against the Bluestaq App Store runtime contract.
#
# Run this before every upload. A green repo loop is not a green upload: this
# builds the actual image and asserts each contract property against it.
#
# POSIX sh only, no bashisms: the platform runs build and test steps under a
# minimal shell, and a step that needs bash dies with "sh: bash: not found".
#
# Usage:
#   scripts/verify-container.sh
#
# Behind a TLS-terminating proxy (a corporate or sandbox egress proxy), pip
# inside the build cannot verify the certificate chain. Point PROXY_CA_BUNDLE at
# the proxy's CA and the script trusts it for the build only; the shipped
# Dockerfile is never modified.
#   PROXY_CA_BUNDLE=/path/to/ca.crt scripts/verify-container.sh
#
# The image is scanned with Grype for High and Critical findings that have a
# fix. Grype reads the CPython interpreter in /usr/local, which Trivy does not,
# and on 0.6.10 it reported the same nine Python CVEs as the App Store's
# Container Scan. Its database comes from grype.anchore.io; if that cannot be
# reached the scan is reported SKIPPED, never passed. SKIP_IMAGE_SCAN=1 skips
# it on purpose.

set -eu

IMAGE="${IMAGE:-spectre:verify}"
CONTAINER="spectre-verify-$$"
HOST_PORT="${HOST_PORT:-18099}"
BUILD_FILE="Dockerfile"
WORK=""

pass() { printf '  PASS  %s\n' "$1"; }
fail() { printf '  FAIL  %s\n' "$1"; exit 1; }

cleanup() {
    docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
    [ -n "$WORK" ] && rm -rf "$WORK"
    return 0
}
trap cleanup EXIT INT TERM

printf '\n== Build ==\n'
if [ -n "${PROXY_CA_BUNDLE:-}" ]; then
    [ -f "$PROXY_CA_BUNDLE" ] || fail "PROXY_CA_BUNDLE is set but $PROXY_CA_BUNDLE does not exist"
    WORK="$(mktemp -d)"
    cp "$PROXY_CA_BUNDLE" ./.verify-proxy-ca.crt
    # The ONLY delta from the shipped Dockerfile: trust the proxy CA so pip can
    # reach the index. Nothing about the runtime contract changes.
    # Matched requirements.lock, which no Dockerfile copies, so nothing was
    # inserted while the note below claimed it was (audit F-176).
    awk '
      /^COPY requirements-runtime\.txt \.\/$/ {
        print "COPY .verify-proxy-ca.crt /tmp/ca.crt"
        print "ENV PIP_CERT=/tmp/ca.crt"
      }
      { print }
    ' Dockerfile > "$WORK/Dockerfile.verify"
    cmp -s Dockerfile "$WORK/Dockerfile.verify" \
        && fail "proxy CA hook matched no line in Dockerfile; the CA would not be trusted"
    cp "$WORK/Dockerfile.verify" ./.Dockerfile.verify
    BUILD_FILE=".Dockerfile.verify"
    printf '  note  building with proxy CA trusted (build-time only)\n'
fi

docker build --network host -f "$BUILD_FILE" -t "$IMAGE" . >/dev/null 2>&1 \
    || { docker build --network host -f "$BUILD_FILE" -t "$IMAGE" .; fail "image build"; }
rm -f ./.verify-proxy-ca.crt ./.Dockerfile.verify
pass "image builds"

printf '\n== Image hardening ==\n'

uid="$(docker run --rm --entrypoint /opt/venv/bin/python "$IMAGE" -c 'import os;print(os.getuid())')"
[ "$uid" = "0" ] && fail "runs as root (uid 0)"
case "$uid" in
    ''|*[!0-9]*) fail "uid is not numeric: $uid" ;;
    *) ;;  # numeric, which is what the platform requires
esac
pass "runs as non-root numeric uid $uid"

# As root, so no directory is unreadable, and without 2>/dev/null, so a find
# that fails is a failure rather than a count of zero (audit F-277).
suid="$(docker run --rm --user 0 --entrypoint /bin/sh "$IMAGE" -c \
    'find / -xdev -perm /6000 \( -type f -o -type d \) -print')" || fail "the setuid/setgid sweep did not run"
[ -z "$suid" ] || { printf '%s\n' "$suid"; fail "setuid/setgid paths ship (container-scan stops on this)"; }
pass "no setuid or setgid paths ship"

for bin in pip pip3 apt apt-get dpkg; do
    if docker run --rm --entrypoint /bin/sh "$IMAGE" -c "command -v $bin" >/dev/null 2>&1; then
        fail "package manager ships in the runtime image: $bin"
    fi
done
pass "no package manager ships"

layers="$(docker inspect "$IMAGE" --format '{{len .RootFS.Layers}}')"
[ "$layers" -le 2 ] || fail "$layers layers: base-image history may still ship"
pass "flattened to $layers layer(s), no base-image history"

printf '\n== Runtime contract ==\n'

secret="$(docker run --rm --entrypoint /opt/venv/bin/python "$IMAGE" \
    -c 'import secrets;print(secrets.token_urlsafe(32))')"

docker run -d --name "$CONTAINER" -p "$HOST_PORT:8080" \
    -e SECRET_KEY="$secret" \
    -e SPECTRE_ADMIN_USER=verify -e SPECTRE_ADMIN_PASS=verify-only-password \
    "$IMAGE" >/dev/null

i=0
while [ "$i" -lt 60 ]; do
    if curl -sf -o /dev/null "http://127.0.0.1:$HOST_PORT/healthz" 2>/dev/null; then break; fi
    i=$((i + 1))
    sleep 1
done
[ "$i" -lt 60 ] || { docker logs "$CONTAINER"; fail "container never became healthy"; }
pass "boots and serves within ${i}s"

# Boot must narrate which storage backend it proved, so a pod that is later
# killed still leaves a diagnosable record. Matches both branches: the durable
# external database and the ephemeral SQLite fallback.
docker logs "$CONTAINER" 2>&1 | grep -qE "storage: (SQLite|external database)" \
    || fail "boot did not narrate its storage backend"
pass "boot narrates its storage backend"

# The platform router probes the root and treats a 302 as a failed deploy.
root="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$HOST_PORT/")"
[ "$root" = "200" ] || fail "GET / returned $root, must be 200"
pass "GET / returns 200"

curl -s "http://127.0.0.1:$HOST_PORT/" | grep -q "Blue Assets" \
    && fail "GET / leaks console state to an anonymous caller"
pass "GET / does not leak console state"

for path in healthz readyz; do
    code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$HOST_PORT/$path")"
    [ "$code" = "200" ] || fail "GET /$path returned $code, must be 200"
    pass "GET /$path returns 200 unauthenticated"
done

docker logs "$CONTAINER" 2>&1 | grep -q "0.0.0.0:8080" \
    || fail "not bound to 0.0.0.0:8080"
pass "bound to 0.0.0.0:8080"

docker rm -f "$CONTAINER" >/dev/null 2>&1 || true

printf '\n== Fail-closed behaviour ==\n'

docker run --rm "$IMAGE" 2>&1 | grep -q "ConfigurationError" \
    || fail "booted without a valid SECRET_KEY"
pass "refuses to boot without SECRET_KEY"

docker run --rm -e SECRET_KEY=change-me "$IMAGE" 2>&1 | grep -q "placeholder" \
    || fail "booted with a placeholder SECRET_KEY"
pass "refuses to boot with a placeholder SECRET_KEY"

printf '\n== Injected PORT ==\n'
docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
docker run -d --name "$CONTAINER" -p "$((HOST_PORT + 1)):9090" -e PORT=9090 \
    -e SECRET_KEY="$secret" "$IMAGE" >/dev/null
i=0
while [ "$i" -lt 45 ]; do
    if curl -sf -o /dev/null "http://127.0.0.1:$((HOST_PORT + 1))/healthz" 2>/dev/null; then break; fi
    i=$((i + 1))
    sleep 1
done
[ "$i" -lt 45 ] || { docker logs "$CONTAINER"; fail "injected PORT was not honoured"; }
pass "honours an injected PORT"

printf '\n== Fixable High and Critical findings (Grype) ==\n'
GRYPE_IMAGE="${GRYPE_IMAGE:-anchore/grype:v0.104.0}"
if [ "${SKIP_IMAGE_SCAN:-0}" = "1" ]; then
    printf '  SKIPPED  SKIP_IMAGE_SCAN=1\n'
else
    # The database is kept in a named volume, so only the first run downloads it.
    set -- --rm -v /var/run/docker.sock:/var/run/docker.sock -v spectre-grype-db:/db \
        -e GRYPE_DB_CACHE_DIR=/db -e GRYPE_CHECK_FOR_APP_UPDATE=false
    if [ -n "${PROXY_CA_BUNDLE:-}" ]; then
        set -- "$@" --network host -v "$PROXY_CA_BUNDLE:/etc/ssl/certs/ca-certificates.crt:ro" \
            -e HTTPS_PROXY="${HTTPS_PROXY:-}" -e HTTP_PROXY="${HTTP_PROXY:-}" -e NO_PROXY="${NO_PROXY:-}"
    fi
    if ! docker run "$@" "$GRYPE_IMAGE" db update >/dev/null 2>&1; then
        printf '  SKIPPED  no Grype database: grype.anchore.io unreachable from here\n'
    else
        findings="$(docker run -i "$@" -e GRYPE_DB_AUTO_UPDATE=false "$GRYPE_IMAGE" "docker:$IMAGE" --only-fixed -q \
            -o template -t /dev/stdin <<'TEMPLATE'
{{- range .Matches }}{{ if or (eq .Vulnerability.Severity "High") (eq .Vulnerability.Severity "Critical") }}
    {{ .Vulnerability.Severity }} {{ .Vulnerability.ID }} {{ .Artifact.Name }} {{ .Artifact.Version }} -> {{ join "," .Vulnerability.Fix.Versions }}
{{- end }}{{ end }}
TEMPLATE
)" || fail "Grype scan did not run"
        if [ -n "$findings" ]; then
            printf '  findings with a fix available:%s\n' "$findings"
            fail "the Container Scan stops on these: take the fix, usually by bumping the base digest"
        fi
        pass "no High or Critical finding has a fix available"
    fi
fi

printf '\nAll container contract checks passed.\n\n'
