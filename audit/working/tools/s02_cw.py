import sys, math
sys.path.insert(0, sys.argv[1])
import numpy as np
from scipy.integrate import solve_ivp
from spectre.astro.tactical import relative_motion_stability
mu=398600.4418; r=7000.0; n=math.sqrt(mu/r**3); T=2*math.pi/n
def cw(t,s):  # x radial, y along-track, z cross-track (Hill)
    x,y,z,vx,vy,vz=s; return [vx,vy,vz, 3*n*n*x+2*n*vy, -2*n*vx, -n*n*z]
s0=[0.0,0.0,0.0, 0.0,0.001,0.0]
sol=solve_ivp(cw,(0,T),s0,rtol=1e-11,atol=1e-12)
true_dy=sol.y[1,-1]-s0[1]
res=relative_motion_stability(r, *s0)
print("numerical CW along-track drift over one orbit (km):", round(true_dy,4))
print("code result:", {k: getattr(res,k) for k in vars(res) if not k.startswith('_')})
