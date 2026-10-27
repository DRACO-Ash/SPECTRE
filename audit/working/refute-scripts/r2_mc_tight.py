import sys, math
sys.path.insert(0, "/tmp/claude-0/-home-user-SPECTRE/e332f7aa-9fda-59a8-9619-1afe89475fea/scratchpad/tree")
import numpy as np
from scipy.integrate import solve_ivp
import spectre.astro.monte_carlo as M
MU, RE = M._MU, M._R_E
a0 = RE+400; v0 = math.sqrt(MU/a0)
st = np.array([a0,0,0,0,v0*math.cos(0.9), v0*math.sin(0.9)])
def sma(bc, H, rtol):
    s = solve_ivp(M._j2_drag_ode, (0, H*3600), st, method="DOP853", rtol=rtol, atol=1e-13, args=(0.0, bc))
    r, v = s.y[:3,-1], s.y[3:,-1]; return M._state_to_keplerian(r, v)[0]
rho0_ER = 2.461e-8*6378.135e3
bc_std = 1/(2*1e-4/rho0_ER); bc_code = 1/(2*1e-4*RE*1e3*2.461e-5)
for H in (6, 48):
    ref = sma(1e12, H, 1e-12)
    dc = sma(bc_code, H, 1e-12)-ref; ds = sma(bc_std, H, 1e-12)-ref
    print(f"H={H} h, J2 on, DOP853 rtol 1e-12: osculating SMA change code BC {dc*1e3:.0f} m, standard BC {ds*1e3:.0f} m, ratio {dc/ds:.2f}")
