import sys, math
sys.path.insert(0, "/tmp/claude-0/-home-user-SPECTRE/e332f7aa-9fda-59a8-9619-1afe89475fea/scratchpad/tree")
import numpy as np
from datetime import datetime, UTC
import spectre.astro.monte_carlo as M
MU, RE = M._MU, M._R_E
print("== F-S04-03 B* conversion")
# Independent derivation: SGP4 defines B* = rho0*B/2 with rho0 = 2.461e-8 kg/m^3 (q0 reference)
# expressed per Earth radius: rho0 = 2.461e-8 kg/m^3 * 6378135 m = 0.156966 kg/m^2/ER ; B = Cd*A/m
rho0_ER = 2.461e-8 * 6378.135e3
for bs in (1e-4, 3e-4):
    B_std = 2*bs/rho0_ER
    bc_code = max(5.0, 1.0 / (2.0 * bs * RE * 1e3 * 2.461e-5))
    print(f"B*={bs:g}: standard Cd*A/m={B_std:.5f} m2/kg (BC {1/B_std:.1f}); code BC={bc_code:.2f} (Cd*A/m {1/bc_code:.5f}); drag ratio code/std={(1/bc_code)/B_std:.2f}")
# Execute the actual propagation and compare decay with an independent analytic rate
h0 = 400.0; a0 = RE + h0; v0 = math.sqrt(MU/a0)
state = np.array([a0, 0, 0, 0, v0*math.cos(math.radians(51.6)), v0*math.sin(math.radians(51.6))])
ric = np.eye(3)
def run(bstar, dt_off=0.0, dv=(0,0,0), H=6.0):
    s = np.array([*dv, dt_off, 0.0])
    return M.propagate_single_sample(s, state, datetime(2026,1,1,tzinfo=UTC), ric, bstar, H)
out = run(1e-4, H=6.0); out0 = run(1e-12, H=6.0)
da_code = out["sma_km"] - out0["sma_km"]
rho = M._atmo_density_kg_m3(h0)
B_std = 2*1e-4/rho0_ER
da_dt = -rho * B_std * math.sqrt(MU*1e9 * a0*1e3)  # m/s, circular-orbit decay da/dt = -rho*B*sqrt(mu*a)
print(f"6 h drag decay at 400 km: code {da_code*1e3:.1f} m; analytic with standard B {da_dt*6*3600:.1f} m; ratio {da_code*1e3/(da_dt*6*3600):.2f}")
print("== F-S04-01 timing")
pos = []
for off in (-30.0, 0.0, 30.0):
    o = run(1e-12, dt_off=off, H=6.0); pos.append(np.array(o["r_final"]))
print("zero dV, offsets -30/0/+30 s: |dr| vs nominal km:", [round(float(np.linalg.norm(p-pos[1])),1) for p in pos], "v*30s =", round(v0*30,1))
print("== F-S04-03 decay with J2 switched off in-process (isolates drag)")
M._J2 = 0.0
out = run(1e-4, H=6.0); out0 = run(1e-12, H=6.0)
da_code = out["sma_km"] - out0["sma_km"]
print(f"6 h drag decay at 400 km (no J2): code {da_code*1e3:.1f} m; analytic standard {da_dt*6*3600:.1f} m; ratio {da_code*1e3/(da_dt*6*3600):.2f}")
out = run(1e-4, H=48.0); out0 = run(1e-12, H=48.0)
print(f"48 h (no J2): code decay {(out['sma_km']-out0['sma_km'])*1e3:.0f} m; analytic standard {da_dt*48*3600:.0f} m; analytic x24.64 {da_dt*48*3600*24.64:.0f} m")
