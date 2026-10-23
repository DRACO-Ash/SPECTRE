import sys
from datetime import datetime, timedelta, UTC
sys.path.insert(0, "/tmp/claude-0/-home-user-SPECTRE/e332f7aa-9fda-59a8-9619-1afe89475fea/scratchpad/tree")
from spectre.astro.events import find_orbital_events, EventType
from spectre.astro.propagator import TLEOrbit
tle = sys.argv[1].replace("\\n", "\n")
o = TLEOrbit(tle)
print("ecco", o._sat.ecco, "rev/day", o._sat.no_kozai*1440/6.283185)
ep = datetime(2024,1,1,tzinfo=UTC)
# use TLE epoch
from sgp4.api import jday
jd = o._sat.jdsatepoch + o._sat.jdsatepochF
ep = datetime(2000,1,1,12,tzinfo=UTC) + timedelta(days=jd-2451545.0)
ev = find_orbital_events(tle, ep, ep+timedelta(days=1), max_per_type=100, step_s=30)
from collections import Counter
print(Counter(e.event_type.value for e in ev))
import numpy as np
P = 86400/15.5424
for e in [x for x in ev if x.event_type == EventType.PERIGEE][:5]:
    ts = [e.epoch + timedelta(seconds=s) for s in np.arange(-P/2, P/2, 10)]
    rs = [o.propagate(t).r_mag for t in ts]
    k = int(np.argmin(rs))
    print(f"perigee event r={o.propagate(e.epoch).r_mag:.2f} km; true local min r={rs[k]:.2f} at offset {(ts[k]-e.epoch).total_seconds():.0f} s; r range in rev {max(rs)-min(rs):.2f} km; n local minima={sum(1 for i in range(1,len(rs)-1) if rs[i]<rs[i-1] and rs[i]<rs[i+1])}")
