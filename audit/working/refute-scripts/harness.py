import os, sys
CLONE="/tmp/claude-0/-home-user-SPECTRE/e332f7aa-9fda-59a8-9619-1afe89475fea/scratchpad/tree"
WORK="/tmp/claude-0/-home-user-SPECTRE/e332f7aa-9fda-59a8-9619-1afe89475fea/scratchpad/refute/work"
os.environ["SECRET_KEY"]="ci-only-ephemeral-signing-key-not-a-secret"
os.environ["DATABASE_URL"]="sqlite+aiosqlite:///:memory:"
os.environ["SPECTRE_ADMIN_USER"]="testadmin"
os.environ["SPECTRE_ADMIN_PASS"]="testpass123"
os.environ["SPECTRE_COOKIE_SECURE"]="false"
os.environ["SPECTRE_DATA_DIR"]=WORK+"/data"
os.environ["SPECTRE_SQLITE_DIR"]=WORK+"/sqlite"
sys.path.insert(0, CLONE)
import anyio, logging
from fastapi.testclient import TestClient
from spectre.web.app import app
from spectre.web.database import init_db
from spectre.web.csrf import make_csrf_token

anyio.run(init_db)

def csrf(cookie): return {"X-CSRF-Token": make_csrf_token(cookie)}

with TestClient(app, raise_server_exceptions=False) as c:
    # login as admin
    r = c.post("/login", data={"username":"testadmin","password":"testpass123"}, follow_redirects=False)
    print("LOGIN admin:", r.status_code, "cookie" in r.headers.get("set-cookie","").lower())
    admin_cookie = r.cookies["spectre_session"]
    ac = {"spectre_session": admin_cookie}

    # ---- F-S08-02 / F-S08-03: create alice, login, delete, recreate, replay old token ----
    h = csrf(admin_cookie)
    r = c.post("/admin/users", data={"username":"alice","password":"alicepass1","role":"operator"}, cookies=ac, headers=h)
    print("create alice:", r.status_code)
    # login as alice
    ra = c.post("/login", data={"username":"alice","password":"alicepass1"}, follow_redirects=False)
    alice_token = ra.cookies["spectre_session"]
    print("alice login:", ra.status_code)
    # confirm alice token works on a protected route
    rr = c.get("/admin/users", cookies={"spectre_session":alice_token}, follow_redirects=False)
    print("alice (operator) GET /admin/users (expect 403):", rr.status_code)
    rp = c.get("/", cookies={"spectre_session":alice_token}, follow_redirects=False)
    print("alice GET / before delete:", rp.status_code)
    # find alice id
    import re
    page = c.get("/admin/users", cookies=ac).text
    # delete alice: need her id
    ids = re.findall(r'/admin/users/(\d+)/edit', page)
    # Map by finding row containing 'alice'
    # Simpler: query db
    from spectre.web.database import AsyncSessionLocal
    from spectre.web.models import User
    from sqlalchemy import select
    async def getid(name):
        async with AsyncSessionLocal() as s:
            u=(await s.execute(select(User).where(User.username==name))).scalar_one_or_none()
            return u.id if u else None
    alice_id = anyio.run(getid, "alice")
    print("alice id:", alice_id)
    rd = c.request("DELETE", f"/admin/users/{alice_id}", cookies=ac, headers=csrf(admin_cookie))
    print("delete alice:", rd.status_code)
    # recreate alice (as admin this time to test role escalation)
    r = c.post("/admin/users", data={"username":"alice","password":"different9","role":"admin"}, cookies=ac, headers=csrf(admin_cookie))
    print("recreate alice as admin:", r.status_code)
    # replay OLD alice token
    rp = c.get("/", cookies={"spectre_session":alice_token}, follow_redirects=False)
    print("REPLAY old alice token GET / :", rp.status_code, "(302=rejected, 200=accepted)")
    radm = c.get("/admin/users", cookies={"spectre_session":alice_token}, follow_redirects=False)
    print("REPLAY old alice token GET /admin/users:", radm.status_code, "(200=accepted as NEW admin alice, 403/302=rejected)")
