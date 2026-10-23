import sys
sys.path.insert(0, "/tmp/claude-0/-home-user-SPECTRE/e332f7aa-9fda-59a8-9619-1afe89475fea/scratchpad/tree")
import numpy as np
from spectre.astro.monte_carlo import check_convergence
rng = np.random.default_rng(0)
for n in (500, 2000):
    ok = sum(check_convergence(list(rng.normal(6778, 2.0, n))) for _ in range(2000))
    print(f"n={n}: iid Gaussian SMA samples flagged converged in {ok/20:.1f}% of 2000 trials")
v = list(rng.normal(6778,2.0,500)); 
print("same values, shuffled order: ", [check_convergence(list(rng.permutation(v))) for _ in range(10)])
# uniform half-width check F-S04-16
print("F-S04-16 uniform 3sigma half-width std/sigma:", np.std(rng.uniform(-3,3,200000)))
# F-S04-10 3D chi: P(r<3 sigma)
from scipy import stats; print("P(|N3|<3σ) =", stats.chi2.cdf(9,3))
