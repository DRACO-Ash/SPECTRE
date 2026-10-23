import sys, logging; sys.path.insert(0, sys.argv[1])
from fastapi.testclient import TestClient
from spectre.web.app import app
recs = []
class H(logging.Handler):
    def emit(self, r): recs.append(r.getMessage())
logging.getLogger("spectre.web.csrf").addHandler(H())
with TestClient(app) as c:
    r = c.delete("/assets/blue/x%0aFORGED Successful login: admin")
    print("status", r.status_code)
for m in recs: print(repr(m))
