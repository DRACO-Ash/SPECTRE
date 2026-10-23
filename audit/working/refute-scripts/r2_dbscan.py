import sys
sys.path.insert(0, "/tmp/claude-0/-home-user-SPECTRE/e332f7aa-9fda-59a8-9619-1afe89475fea/scratchpad/tree")
from datetime import datetime, timedelta, UTC
from tle_clustering.models import TLERecord
from tle_clustering.clustering import cluster_records
from tle_clustering.config import ClusteringConfig
from spectre.config.constants import TLE_CLUSTERING
cfg = ClusteringConfig.from_constants(TLE_CLUSTERING)
t0 = datetime(2026,1,1,tzinfo=UTC)
recs = []
for k in range(8):              # every 3 h over 24 h, two providers each
    for p, d in ((0, 0.0), (1, 0.003)):
        ep = t0 + timedelta(hours=3*k, minutes=2*p)
        recs.append(TLERecord(25544, f"L1-{k}-{p}", "L2", ep, 51.64+d/10, 100.0 - 5.0*3*k/24 + d, 0.0005))
res = cluster_records(25544, recs, cfg)
print("clusters", len(res.clusters), "noise", len(res.noise))
print("first cluster rep epoch", res.clusters[0].representative.epoch, "latest input epoch", recs[-1].epoch)
# reversed input order
res2 = cluster_records(25544, list(reversed(recs)), cfg)
print("reversed input: first cluster rep epoch", res2.clusters[0].representative.epoch)
