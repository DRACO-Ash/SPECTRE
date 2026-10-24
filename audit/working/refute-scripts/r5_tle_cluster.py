"""R5: tle_clustering RAAN seam (F-S09-10), multi-epoch LEO (F-S09-11), chaining (F-S09-12)."""
import sys, math
sys.path.insert(0, sys.argv[1])
from sgp4.api import Satrec
from tle_clustering import cluster_tle_strings
from tle_clustering.config import ClusteringConfig


def cks(line):
    s = 0
    for ch in line[:68]:
        if ch.isdigit():
            s += int(ch)
        elif ch == "-":
            s += 1
    return str(s % 10)


def mk(satno, epoch_day, inc, raan, ecc, argp, ma, n, yy=26):
    l1 = f"1 {satno:05d}U 98067A   {yy:02d}{epoch_day:012.8f}  .00016717  00000-0  10270-3 0  999"
    l1 = l1[:68] + cks(l1[:68])
    ecc_s = f"{ecc:.7f}"[2:]
    l2 = f"2 {satno:05d} {inc:8.4f} {raan % 360:8.4f} {ecc_s} {argp % 360:8.4f} {ma % 360:8.4f} {n:11.8f}{10000:5d}"
    l2 = l2[:68] + cks(l2[:68])
    assert len(l1) == 69 and len(l2) == 69, (len(l1), len(l2))
    return l1, l2


def run(label, pairs, cfg=None):
    lines = [x for p in pairs for x in p]
    res = cluster_tle_strings(lines, cfg)
    for nid, r in res.items():
        print(f"{label}: tles={r.total_tles_in} clusters={r.cluster_count} noise={r.noise_count}",
              [(c.size, round(c.centroid_raan_deg, 4)) for c in r.clusters])


# F-S09-10: RAAN seam
seam = [mk(25544, 91.5, 51.64, 359.99, 0.0001207, 87.0, 273.0, 15.5),
        mk(25544, 91.5, 51.64, 0.01, 0.0001207, 87.0, 273.0, 15.5)]
run("seam 359.99/0.01", seam)
seam3 = [mk(25544, 91.5, 51.64, r, 0.0001207, 87.0, 273.0, 15.5) for r in (359.98, 359.99, 0.01)]
run("seam 359.98/359.99/0.01", seam3)
ctrl = [mk(25544, 91.5, 51.64, r, 0.0001207, 87.0, 273.0, 15.5) for r in (179.98, 179.99, 180.01)]
run("control 179.98/179.99/180.01", ctrl)

# F-S09-11: one ISS-like orbit sampled over 24 h with RAAN advanced at SGP4's own secular rate
base = mk(25544, 91.0, 51.64, 200.0, 0.0001207, 87.0, 273.0, 15.5)
sat = Satrec.twoline2rv(*base)
node_rate_deg_day = math.degrees(sat.nodedot) * 1440.0
argp_rate_deg_day = math.degrees(sat.argpdot) * 1440.0
print("SGP4 secular nodal rate deg/day:", round(node_rate_deg_day, 4), " argp rate:", round(argp_rate_deg_day, 4))
for step_min in (10, 15, 40, 120):
    pairs = []
    t = 0.0
    while t <= 1440.0 + 1e-9:
        d = t / 1440.0
        pairs.append(mk(25544, 91.0 + d, 51.64, 200.0 + node_rate_deg_day * d, 0.0001207,
                        87.0 + argp_rate_deg_day * d, 273.0 + 360 * 15.5 * d, 15.5))
        t += step_min
    run(f"24h LEO every {step_min} min", pairs)
# realistic: 30 TLEs at random-ish epochs over 24h from several providers
import random
random.seed(1)
eps = sorted(random.uniform(0, 1) for _ in range(30))
pairs = [mk(25544, 91.0 + d, 51.64 + random.gauss(0, 0.002), 200.0 + node_rate_deg_day * d + random.gauss(0, 0.005),
            0.0001207 + random.gauss(0, 1e-5), 87.0, 273.0, 15.5) for d in eps]
run("24h LEO 30 random epochs, small noise", pairs)
# GEO over 24h: nodal rate is tiny
geo = Satrec.twoline2rv(*mk(40000, 91.0, 0.05, 80.0, 0.0002, 90.0, 0.0, 1.0027, ))
print("GEO nodal rate deg/day:", math.degrees(geo.nodedot) * 1440.0)

# F-S09-12: chaining in inclination stepped at 0.9 tolerance
chain = [mk(25544, 91.5, 51.64 + 0.009 * k, 200.0, 0.0001207, 87.0, 273.0, 15.5) for k in range(5)]
run("chain 5 x 0.9 tol in inc", chain)
