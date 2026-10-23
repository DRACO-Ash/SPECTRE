import sys
sys.path.insert(0, "/tmp/claude-0/-home-user-SPECTRE/e332f7aa-9fda-59a8-9619-1afe89475fea/scratchpad/tree")
from spectre.astro.propagator import TLEOrbit
from spectre.data.intel import satno_from_tle
l1="1 25544U 98067A   20194.88612269 -.00002218  00000-0 -31515-4 0  9992"
l2="2 25544  51.6461 221.2784 0001413  89.1723 280.4612 15.49507896236008"
def fix(l):
    s=sum(int(c) if c.isdigit() else (1 if c=='-' else 0) for c in l[:68]); return l[:68]+str(s%10)
a1=fix("1 A5544"+l1[7:]); a2=fix("2 A5544"+l2[7:])
for tle in (l1+"\n"+l2, a1+"\n"+a2):
    try:
        TLEOrbit(tle); print("accepted", repr(str(satno_from_tle(tle))))
    except Exception as e: print("rejected", type(e).__name__, e)
