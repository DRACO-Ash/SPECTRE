import sys, time, os
sys.path.insert(0, "/tmp/claude-0/-home-user-SPECTRE/e332f7aa-9fda-59a8-9619-1afe89475fea/scratchpad/tree")
sys.path.insert(0, "/tmp/claude-0/-home-user-SPECTRE/e332f7aa-9fda-59a8-9619-1afe89475fea/scratchpad/tree/tests/unit")
import test_monte_carlo as T
from spectre.astro.monte_carlo import run_monte_carlo
print("cpus", os.cpu_count())
for w in (1, 4):
    h = T._basic_hypothesis(n_samples=40)
    t = time.monotonic(); run_monte_carlo(h, satno=1, prediction_horizon_hours=6.0, max_workers=w); print("workers", w, round(time.monotonic()-t,2), "s")
