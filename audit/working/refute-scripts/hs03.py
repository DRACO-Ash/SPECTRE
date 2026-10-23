import os, sys
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
from spectre.web.database import init_db, AsyncSessionLocal
from spectre.web.models import User
from spectre.web.csrf import make_csrf_token
from spectre.web import planning_state
from sqlalchemy import select
anyio.run(init_db)
def csrf(cookie): return {"X-CSRF-Token": make_csrf_token(cookie)}
with TestClient(app, raise_server_exceptions=False) as c:
    r=c.post("/login",data={"username":"testadmin","password":"testpass123"},follow_redirects=False)
    ac={"spectre_session":r.cookies["spectre_session"]}; tok=r.cookies["spectre_session"]
    c.post("/admin/users",data={"username":"bob","password":"bobpass1234","role":"operator"},cookies=ac,headers=csrf(tok))
    # simulate bob having UDL creds in his session state
    st = planning_state.get_session_state("bob")
    st.udl_username="bob_udl"; st.udl_password="SECRET_UDL_PW"
    print("before delete: _store has bob:", "bob" in planning_state._store, "udl_pw set:", planning_state._store["bob"].udl_password is not None)
    async def getid():
        async with AsyncSessionLocal() as s:
            return (await s.execute(select(User).where(User.username=="bob"))).scalar_one().id
    bid=anyio.run(getid)
    c.request("DELETE",f"/admin/users/{bid}",cookies=ac,headers=csrf(tok))
    print("after delete: _store still has bob:", "bob" in planning_state._store,
          "| udl_pw still set:", planning_state._store.get("bob") and planning_state._store["bob"].udl_password)
