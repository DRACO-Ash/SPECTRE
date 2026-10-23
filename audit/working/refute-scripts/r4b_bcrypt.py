import sys; sys.path.insert(0, sys.argv[1])
import bcrypt; print("bcrypt", bcrypt.__version__)
from spectre.web.auth import hash_password, verify_password
h = hash_password("short")
for name, fn in [("verify long", lambda: verify_password("x"*100, h)), ("hash long", lambda: hash_password("x"*100)), ("verify 72", lambda: verify_password("x"*72, h))]:
    try: print(name, "->", fn())
    except Exception as e: print(name, "RAISES", type(e).__name__, e)
