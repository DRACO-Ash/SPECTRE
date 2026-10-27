import sys, os
sys.path.insert(0, sys.argv[1]); os.environ.setdefault("SECRET_KEY","ci-only-ephemeral-signing-key-not-a-secret")
from spectre.web.routes import udl
recs=[{"createdAt":"2026-01-01T00:00:00.000Z"},{"createdAt":"2026-01-02T00:00:00"}]
try: print(max(recs,key=udl._parse_created_at))
except Exception as e: print("max:",type(e).__name__, e)
for ep in ["26000.50000000","26400.00000000","56001.00000000","00001.00000000"]:
    l1="1 25544U 98067A   "+ep+"  .00000000  00000-0  00000-0 0  9999"
    print(ep, udl._parse_tle_epoch(l1))
