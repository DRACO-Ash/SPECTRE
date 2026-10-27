import sys, re; sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[1]+"/tests")
from fastapi.testclient import TestClient
from spectre.web.app import app
from spectre.web.csrf import make_csrf_token
H = lambda c: {"X-CSRF-Token": make_csrf_token(c["spectre_session"])}
def login(c, u, p):
    r = c.post("/login", data={"username": u, "password": p}, follow_redirects=False); return dict(r.cookies), r.status_code
with TestClient(app) as c:
    adm, s = login(c, "admin", "some-admin-pass"); print("admin login", s)
    print("create", c.post("/admin/users", data={"username":"alice","password":"pw1","role":"operator"}, cookies=adm, headers=H(adm)).status_code)
    old, s = login(c, "alice", "pw1"); print("alice login", s)
    page = c.get("/admin/users", cookies=adm).text
    uid = re.findall(r'/admin/users/(\d+)/edit', page)
    for u in uid:
        if "alice" in c.get(f"/admin/users/{u}/edit", cookies=adm).text: break
    print("delete", c.delete(f"/admin/users/{u}", cookies=adm, headers=H(adm)).status_code)
    print("old cookie after delete", c.get("/admin/users", cookies=old, follow_redirects=False).status_code)
    print("recreate as admin", c.post("/admin/users", data={"username":"alice","password":"pw2","role":"admin"}, cookies=adm, headers=H(adm)).status_code)
    r = c.get("/admin/users", cookies=old, follow_redirects=False)
    print("old cookie after recreate -> /admin/users", r.status_code, r.headers.get("location"))
