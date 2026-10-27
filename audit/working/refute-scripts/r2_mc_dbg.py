import sys, math
sys.path.insert(0, "/tmp/claude-0/-home-user-SPECTRE/e332f7aa-9fda-59a8-9619-1afe89475fea/scratchpad/tree")
import numpy as np
import spectre.astro.monte_carlo as M
M._J2 = 0.0
MU, RE = M._MU, M._R_E
a0 = RE+400; v0 = math.sqrt(MU/a0)
st = np.array([a0,0,0,0,v0,0.0])
bc = 31.85
d = M._j2_drag_ode(0.0, st, 1e-4, bc) if M._j2_drag_ode.__code__.co_varnames[0]=='t' else None
print(M._j2_drag_ode.__code__.co_varnames[:4])
d = M._j2_drag_ode(0.0, st, 1e-4, bc)
a_tot = d[3:]; a2b = -(MU/a0**3)*st[:3]
adrag = a_tot - a2b
rho = M._atmo_density_kg_m3(400)
print("a_drag code km/s2", adrag, "expected 0.5*rho*v^2/BC", 0.5*rho*(v0*1e3)**2/bc*1e-3)
# da/dt implied
print("da/dt (m/s) = 2 a^2 v . a_drag / mu", 2*(a0)**2*(v0*adrag[1])/MU*1e3, " -> 6h", 2*(a0)**2*(v0*adrag[1])/MU*1e3*21600)
