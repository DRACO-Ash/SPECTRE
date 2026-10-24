import sys, logging, asyncio; sys.path.insert(0, sys.argv[1])
from spectre.web.app import app
recs = []
class H(logging.Handler):
    def emit(self, r): recs.append(r.getMessage())
logging.getLogger("spectre.web.csrf").addHandler(H())
async def main():
    # Scope as uvicorn builds it: path = unquote(raw_path)
    from urllib.parse import unquote
    raw = b"/assets/blue/x%0aFORGED"
    scope = {"type":"http","asgi":{"version":"3.0"},"http_version":"1.1","method":"DELETE","scheme":"http",
             "path":unquote(raw.decode()),"raw_path":raw,"root_path":"","query_string":b"","headers":[(b"host",b"t")],
             "client":("1.2.3.4",1),"server":("t",80)}
    out=[]
    async def recv(): return {"type":"http.request","body":b"","more_body":False}
    async def send(m): out.append(m)
    await app(scope, recv, send)
    print("status", [m.get("status") for m in out if m["type"]=="http.response.start"])
asyncio.run(main())
for m in recs: print(repr(m))
