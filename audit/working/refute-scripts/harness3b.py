import sys
CLONE="/tmp/claude-0/-home-user-SPECTRE/e332f7aa-9fda-59a8-9619-1afe89475fea/scratchpad/tree"
sys.path.insert(0, CLONE)
from starlette.requests import Request
import starlette
print("starlette", starlette.__version__)
scope={"type":"http","method":"DELETE","path":"/a/x\nFORGED","headers":[],"query_string":b"","scheme":"http","server":("t",80)}
r=Request(scope, None)
print("request.url.path repr:", repr(r.url.path))
print("scope path repr:", repr(scope["path"]))
