"""R5: scenario objective sums vs passing/optimal (F-S09-07), GEO longitude (F-S09-08), TLE checksums (F-S09-33), challenge levels (F-S09-23), unlock targets (F-S09-22)."""
import sys, math
sys.path.insert(0, sys.argv[1])
from spectre.training.scenarios import load_scenarios
from spectre.training.gamification import get_config
sc = load_scenarios()
for s in sc:
    tot = sum(o.points for o in s.objectives)
    flag = []
    if tot < s.scoring.passing_score: flag.append("UNPASSABLE")
    if tot < s.scoring.optimal_score: flag.append("optimal>max")
    print(f"{s.id:40s} L{s.level_required} ch={s.challenge} sum={tot} pass={s.scoring.passing_score} opt={s.scoring.optimal_score} {flag}")
    noans = sum(o.points for o in s.objectives if not o.answer)
    print("      self-cert points:", noans)
# checksums
def cks(line):
    s = 0
    for ch in line[:68]:
        if ch.isdigit(): s += int(ch)
        elif ch == '-': s += 1
    return s % 10
bad = tot_lines = 0
for s in sc:
    for o in s.objects:
        for ln in [x for x in o.tle.splitlines() if x[:2] in ('1 ','2 ')]:
            tot_lines += 1
            if len(ln) < 69 or not ln[68].isdigit() or int(ln[68]) != cks(ln):
                bad += 1
print("TLE lines", tot_lines, "bad checksum", bad)
# cadet_01 longitude
from sgp4.api import Satrec, jday
s0 = [s for s in sc if s.id == "cadet_01_geo_stationkeeping"][0]
l1, l2 = [x for x in s0.objects[0].tle.splitlines() if x[:2] in ('1 ','2 ')]
print(repr(l1)); print(repr(l2)); print("cks expected", cks(l1), cks(l2))
sat = Satrec.twoline2rv(l1, l2)
jd, fr = jday(2025, 6, 15, 0, 0, 0)
e, r, v = sat.sgp4(jd, fr)
# GMST IAU-82
T = ((jd + fr) - 2451545.0) / 36525
gmst = (67310.54841 + (876600*3600 + 8640184.812866)*T + 0.093104*T*T - 6.2e-6*T**3) % 86400 / 240.0
lon_teme = math.degrees(math.atan2(r[1], r[0])) % 360
print("err", e, "GMST deg", gmst, "TEME RA", lon_teme, "east lon", (lon_teme - gmst) % 360)
print("raan+argp+M", (math.degrees(sat.nodeo + sat.argpo + sat.mo) - gmst) % 360)
cfg = get_config()
ids = {s.id: s.level_required for s in sc}
for lv in cfg.levels:
    for u in lv.unlocks:
        k, _, n = u.partition(":")
        if k in ("scenario", "challenge"):
            print("L", lv.level, u, "exists" if n in ids else "MISSING", ids.get(n))
