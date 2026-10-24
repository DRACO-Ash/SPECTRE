"""Targeted mutation sample. Usage: mutate.py <clone> <venv-python> <out.md>
Each mutant replaces one exact substring on one line; the line must match first."""
import subprocess, sys, os, time
clone, py, out = sys.argv[1:4]
ENV = dict(os.environ, SECRET_KEY="ci-only-ephemeral-signing-key-not-a-secret")
TESTS = {
 "spectre/astro/transfers.py": ["tests/unit/test_astro.py", "tests/unit/test_tactical.py", "tests/unit/test_tactical_validation.py", "tests/unit/test_threat_sweep.py", "tests/unit/test_orbital_units_and_degeneracies.py", "tests/integration/test_web_routes_extended.py", "tests/unit/test_intercept_envelope.py"],
 "spectre/web/csrf.py": ["tests/unit/test_csrf.py", "tests/integration/"],
 "spectre/web/auth.py": ["tests/unit/test_auth.py", "tests/integration/"],
}
M = [
 ("transfers.py", 33, "2.0 / r - 1.0 / a", "2.0 / r + 1.0 / a", "vis-viva sign"),
 ("transfers.py", 47, "(r1 + r2) / 2.0", "(r1 + r2) / 2.1", "Hohmann transfer SMA scaled by 0.95"),
 ("transfers.py", 49, "math.sqrt(mu / r1)", "math.sqrt(mu / r1) * 1.03", "Hohmann circular speed +3%"),
 ("transfers.py", 56, "math.pi * math.sqrt", "1.04 * math.pi * math.sqrt", "Hohmann transfer time +4%"),
 ("transfers.py", 55, "abs(v2 - v_t_a)", "abs(v2 - v_t_a) * 1.04", "Hohmann second burn +4%"),
 ("transfers.py", 80, "(r1 + rb) / 2.0", "(r1 + rb) / 2.2", "bi-elliptic first SMA wrong"),
 ("transfers.py", 92, "abs(v_t2_a - v_t1_a)", "abs(v_t2_a + v_t1_a)", "bi-elliptic apoapsis burn sign"),
 ("transfers.py", 93, "abs(v2 - v_t2_p)", "abs(v2 - v_t2_p) * 2.0", "bi-elliptic third burn doubled"),
 ("transfers.py", 94, "+ math.pi * math.sqrt(a2**3 / mu)", "+ math.pi * math.sqrt(a1**3 / mu)", "bi-elliptic second leg uses a1"),
 ("transfers.py", 28, "self.delta_v_1 + self.delta_v_2 + self.delta_v_3", "self.delta_v_1 + self.delta_v_2", "total omits third burn"),
 ("csrf.py", 24, '"GET", "HEAD", "OPTIONS", "TRACE"', '"GET", "HEAD", "OPTIONS", "TRACE", "DELETE"', "DELETE treated as safe"),
 ("csrf.py", 25, 'frozenset({"/login"})', 'frozenset({"/login", "/logout"})', "logout exempted"),
 ("csrf.py", 46, "hashlib.sha256(session_cookie.encode()).hexdigest()", '"fixed"', "token not bound to session"),
 ("csrf.py", 57, "if not submitted or not session_cookie:", "if not submitted:", "empty-session token accepted path"),
 ("csrf.py", 62, "return False", "return True", "bad signature accepted"),
 ("csrf.py", 91, 'token = ""', 'token = "x"', "form-parse failure token"),
 ("auth.py", 22, "_SESSION_MAX_AGE = 28_800", "_SESSION_MAX_AGE = 28_800 * 1000", "session never expires"),
 ("auth.py", 102, "return generation < (user.session_generation or 0)", "return False", "revocation disabled"),
 ("auth.py", 159, 'if current_user.role != "admin":', 'if current_user.role == "nobody":', "admin check disabled"),
 ("auth.py", 195, "if user is None or _session_revoked(user, generation):", "if user is None:", "optional_login ignores revocation"),
 ("auth.py", 141, "if _session_revoked(user, generation):", "if False:", "require_login ignores revocation"),
]
rows = []
for short, ln, old, new, label in M:
    f = next(k for k in TESTS if k.endswith(short)); p = os.path.join(clone, f)
    src = open(p).read().split("\n"); line = src[ln - 1]
    if old not in line:
        rows.append((short, ln, label, "NOT-APPLIED (line mismatch)", "")); continue
    src[ln - 1] = line.replace(old, new, 1); open(p, "w").write("\n".join(src))
    t0 = time.time()
    r = subprocess.run([py, "-m", "pytest", "-o", "addopts=", "-p", "no:cacheprovider", "-q", "-x", "-W", "ignore", *TESTS[f]], cwd=clone, env=ENV, capture_output=True, text=True, timeout=900)
    subprocess.run(["git", "checkout", "-q", f], cwd=clone, check=True)
    tail = [l for l in r.stdout.splitlines() if "passed" in l or "failed" in l or "error" in l.lower()][-1:] or ["?"]
    killer = next((l.split(" ")[1] for l in r.stdout.splitlines() if l.startswith("FAILED ")), "")
    rows.append((short, ln, label, "KILLED" if r.returncode != 0 else "SURVIVED", (killer or tail[0])[:110]))
    print(rows[-1], f"{time.time()-t0:.0f}s", flush=True)
with open(out, "w") as fh:
    fh.write("| File:line | Mutant | Result | Evidence (first failing test, or summary) |\n|---|---|---|---|\n")
    for s, l, lab, res, ev in rows: fh.write(f"| `{s}:{l}` | {lab} | **{res}** | `{ev}` |\n")
    k = sum(r[3] == "KILLED" for r in rows); s = sum(r[3] == "SURVIVED" for r in rows)
    fh.write(f"\nKilled {k}, survived {s}, not applied {len(rows)-k-s}, of {len(rows)}.\n")
