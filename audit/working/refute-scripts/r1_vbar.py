import math, sys
sys.argv = ["x"]
exec(open("r1_checks.py").read().split("# F-S01-03")[0])
ORBITS["b2"] = (7000.0, 51.6, 10.0, 0.0)
ORBITS["r2"] = (7000.0, 51.6, 10.0, -0.5)
for nh in (3, 2):
    s = M.vbar_hop_intercept("r2", "b2", EPOCH, n_hops=nh)
    b1, b2 = s.burns[0].dv_radial, s.burns[1].dv_radial
    xdot_end = b1 * math.cos(math.pi * nh) + b2
    print(f"vbar n_hops={nh}: burn1 radial={b1*1000:.3f} burn2 radial={b2*1000:.3f} m/s; residual xdot={xdot_end*1000:.3f} m/s")
