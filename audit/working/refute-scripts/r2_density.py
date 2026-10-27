import sys
sys.path.insert(0, "/tmp/claude-0/-home-user-SPECTRE/e332f7aa-9fda-59a8-9619-1afe89475fea/scratchpad/tree")
from spectre.astro.monte_carlo import _atmo_density_kg_m3 as rho
for h in (86,150,200,300,400,500,700,1000):
    lo, hi = rho(h-1e-6), rho(h)
    print(f"band edge {h} km: just below {lo:.3e}, at edge {hi:.3e}, jump x{hi/lo:.2f}")
print("550 km", f"{rho(550):.3e}", "700 km", f"{rho(700):.3e}")
