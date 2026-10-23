import os, sys, logging, io, asyncio
CLONE="/tmp/claude-0/-home-user-SPECTRE/e332f7aa-9fda-59a8-9619-1afe89475fea/scratchpad/tree"
os.environ.update(SECRET_KEY="ci-only-ephemeral-signing-key-not-a-secret")
sys.path.insert(0, CLONE)
from starlette.requests import Request
from spectre.web import csrf

buf = io.StringIO()
h = logging.StreamHandler(buf); h.setLevel(logging.WARNING)
csrf.logger.addHandler(h); csrf.logger.setLevel(logging.WARNING)

# craft an ASGI scope with a newline already in the decoded path (what uvicorn
# would hand us if it percent-decoded %0a)
async def recv(): return {"type":"http.request","body":b"","more_body":False}
scope={"type":"http","method":"DELETE","path":"/assets/blue/x\nFORGED-ENTRY 200 OK",
       "headers":[], "query_string":b"", "scheme":"http","server":("t",80),"client":("1.2.3.4",9)}
req=Request(scope, recv)
try:
    asyncio.get_event_loop().run_until_complete(csrf.require_csrf(req))
except Exception as e:
    print("raised:", type(e).__name__)
print("log repr:", repr(buf.getvalue()))
print("line count:", buf.getvalue().count("\n"))
