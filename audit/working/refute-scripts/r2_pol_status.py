import sys, math
sys.path.insert(0, "/tmp/claude-0/-home-user-SPECTRE/e332f7aa-9fda-59a8-9619-1afe89475fea/scratchpad/tree")
sys.path.insert(0, "/tmp/claude-0/-home-user-SPECTRE/e332f7aa-9fda-59a8-9619-1afe89475fea/scratchpad/tree/tests/unit")
from datetime import timedelta
from spectre.astro.pattern_of_life import _pol_status_and_reason, _pol_stats
import test_pol_status_ladder as T
for n in range(2, 14):
    dvs = [0.001]*(n-1) + [0.1]   # last is 100x the rest
    ms = [T._manoeuvre(d) for d in dvs]
    st = _pol_stats(dvs)
    z = (dvs[-1]-st.mean)/st.std
    status,_ = _pol_status_and_reason(T._BURN + timedelta(days=1), ms, st)
    print(n, round(z,3), "bound", round((n-1)/math.sqrt(n),3), status)
# reviewer hand check [1,100] m/s
dvs=[0.001,0.1]; st=_pol_stats(dvs); print("hand", st.mean, st.std, (0.1-st.mean)/st.std)
