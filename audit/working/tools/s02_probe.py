import sys, math
sys.path.insert(0, sys.argv[1])
from spectre.astro.tactical import min_time_intercept_analytical, relative_motion_stability
from spectre.astro.constants import MU_EARTH
for r1, r2, b in [(7000.0, 8000.0, 2.0), (6778.0, 7178.0, 1.0), (6778.0, 42164.0, 5.0)]:
    r = min_time_intercept_analytical(r1, r2, b)
    print(f"min_time r1={r1} r2={r2} budget={b}: tof={r.min_tof_s:.1f}s dv={r.delta_v_km_s:.4f} hohmann_tof={r.hohmann_tof_s:.1f}s hohmann_dv={r.hohmann_dv_km_s:.4f} ratio={r.min_tof_s/r.hohmann_tof_s:.4f}")
import inspect; print("stability sig:", inspect.signature(relative_motion_stability))
