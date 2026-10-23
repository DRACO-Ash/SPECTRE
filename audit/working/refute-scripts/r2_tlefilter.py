import sys
sys.path.insert(0, "/tmp/claude-0/-home-user-SPECTRE/e332f7aa-9fda-59a8-9619-1afe89475fea/scratchpad/tree")
sys.path.insert(0, "/tmp/claude-0/-home-user-SPECTRE/e332f7aa-9fda-59a8-9619-1afe89475fea/scratchpad/tree/tests/unit")
from datetime import timedelta
import test_tle_filter as T
from spectre.astro.tle_filter import filter_tle_history, cluster_tles
for n in (6, 12):
    recs = [T._make_record(T._T0 + timedelta(minutes=10*i)) for i in range(n)]
    reps, flags = filter_tle_history(recs)
    print(f"{n} sets 10 min apart (span {10*(n-1)} min): clusters={len(cluster_tles(recs))}, reps={len(reps)}, flags={[f.flag_type for f in flags]}")
