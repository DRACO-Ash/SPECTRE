import os, sys, logging, io
CLONE="/tmp/claude-0/-home-user-SPECTRE/e332f7aa-9fda-59a8-9619-1afe89475fea/scratchpad/tree"
WORK="/tmp/claude-0/-home-user-SPECTRE/e332f7aa-9fda-59a8-9619-1afe89475fea/scratchpad/refute/work"
os.environ.update(SECRET_KEY="ci-only-ephemeral-signing-key-not-a-secret",
  DATABASE_URL="sqlite+aiosqlite:///:memory:", SPECTRE_ADMIN_USER="testadmin",
  SPECTRE_ADMIN_PASS="testpass123", SPECTRE_COOKIE_SECURE="false",
  SPECTRE_DATA_DIR=WORK+"/data", SPECTRE_SQLITE_DIR=WORK+"/sqlite")
sys.path.insert(0, CLONE)
import anyio
from fastapi.testclient import TestClient
from spectre.web.app import app
from spectre.web.database import init_db
from spectre.web.csrf import make_csrf_token
anyio.run(init_db)
def csrf(cookie): return {"X-CSRF-Token": make_csrf_token(cookie)}

# capture CSRF logger
buf = io.StringIO()
h = logging.StreamHandler(buf); h.setLevel(logging.WARNING)
logging.getLogger("spectre.web.csrf").addHandler(h)
logging.getLogger("spectre.web.csrf").setLevel(logging.WARNING)

with TestClient(app, raise_server_exceptions=False) as c:
    # ---- F-S08-06: long password (>72 bytes) at /login ----
    r = c.post("/login", data={"username":"testadmin","password":"x"*100}, follow_redirects=False)
    print("F-S08-06 login 100-byte password:", r.status_code, "(500=bug, 401=handled)")

    # ---- F-S08-07: login CSRF / origin check ----
    r = c.post("/login", data={"username":"testadmin","password":"testpass123"},
               headers={"Origin":"https://evil.example"}, follow_redirects=False)
    print("F-S08-07 login with evil Origin:", r.status_code, "(302=no origin check, 403=checked)")

    # ---- F-S08-04: CSRF log newline injection via decoded path ----
    buf.truncate(0); buf.seek(0)
    r = c.request("DELETE", "/assets/blue/x%0aFORGED-ENTRY", follow_redirects=False)
    print("F-S08-04 DELETE with %0a path, status:", r.status_code)
    logged = buf.getvalue()
    print("  log lines count:", logged.count("\n"))
    print("  repr of log:", repr(logged))

    # ---- F-S08-08: logout with revoked-but-unexpired token ----
    # login as admin (session gen g)
    r = c.post("/login", data={"username":"testadmin","password":"testpass123"}, follow_redirects=False)
    tokA = r.cookies["spectre_session"]
    # legit logout (bumps generation -> tokA revoked)
    c.post("/logout", cookies={"spectre_session":tokA}, headers=csrf(tokA), follow_redirects=False)
    # tokA should now be revoked for protected routes
    rprot = c.get("/admin/users", cookies={"spectre_session":tokA}, follow_redirects=False)
    print("F-S08-08 revoked tokA GET /admin/users:", rprot.status_code, "(302=revoked ok)")
    # login as admin again -> fresh session tokB
    r = c.post("/login", data={"username":"testadmin","password":"testpass123"}, follow_redirects=False)
    tokB = r.cookies["spectre_session"]
    rb = c.get("/admin/users", cookies={"spectre_session":tokB}, follow_redirects=False)
    print("  fresh tokB GET /admin/users:", rb.status_code)
    # attacker replays logout with revoked tokA (mint csrf for tokA - render mints for any cookie)
    rlo = c.post("/logout", cookies={"spectre_session":tokA}, headers=csrf(tokA), follow_redirects=False)
    print("  attacker logout with revoked tokA:", rlo.status_code)
    # did it revoke tokB?
    rb2 = c.get("/admin/users", cookies={"spectre_session":tokB}, follow_redirects=False)
    print("  tokB after attacker logout:", rb2.status_code, "(302=tokB KILLED by attacker, 200=survived)")
