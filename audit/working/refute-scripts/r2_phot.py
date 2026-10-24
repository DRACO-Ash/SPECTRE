import sys, math, random
sys.path.insert(0, "/tmp/claude-0/-home-user-SPECTRE/e332f7aa-9fda-59a8-9619-1afe89475fea/scratchpad/tree")
import numpy as np
from scipy import stats
from datetime import datetime, timedelta, UTC
import spectre.astro.photometry as P
T0 = datetime(2026,1,1,tzinfo=UTC)
def obs(day, mag, phase):
    return P.PhotometryObservation(T0+timedelta(days=day), mag, 0.05, "V", 51.0, 0.0, 0.0, 1000.0, phase, 60.0, 0.0, 120.0)
rng = random.Random(1)
print("== F-S04-05 confidence vs p")
for shift in (0.0, 0.01, 0.02):
    o = [obs(d*0.5, 8.0 + 0.02*(20+ (d%40)) + (shift if d*0.5 >= 90 else 0) + rng.gauss(0,0.05), 20+(d%40)) for d in range(240)]
    a = P.assess_photometry(o)
    print(f"shift {shift}: p={a.p_value:.4f} confidence={a.confidence} 1-p={1-a.p_value:.4f} sig95={a.significant_at_95}")
print("== F-S04-08 Welch df guard, n=3000, sigma=0.05")
r = np.random.default_rng(0)
A = list(r.normal(0,0.05,3000)); B = list(r.normal(0.004,0.05,3000))
t,p = P._t_test_two_sample(A,B); ref = stats.ttest_ind(A,B,equal_var=False)
va, vb = np.var(A,ddof=1), np.var(B,ddof=1)
print(f"denom={(va/3000)**2/2999+(vb/3000)**2/2999:.3e}; code t={t:.3f} p={p:.4f}; scipy t={ref.statistic:.3f} p={ref.pvalue:.6f}")
A = list(r.normal(0,0.5,30)); B = list(r.normal(0.3,0.5,30))
t,p = P._t_test_two_sample(A,B); ref = stats.ttest_ind(A,B,equal_var=False)
print(f"control n=30 sigma=0.5: code p={p:.6f} scipy p={ref.pvalue:.6f}")
print("== F-S04-09 covariance")
ph = list(np.linspace(10,60,50)); mg = [8+0.02*x+1e-4*x*x + r.normal(0,0.05) for x in ph]
a0,a1,a2,cov = P._fit_least_squares_quadratic(ph, mg)
X = np.column_stack([np.ones(50), ph, np.square(ph)]); res = np.array(mg)-X@np.array([a0,a1,a2]); s2 = res@res/47
true = s2*np.linalg.inv(X.T@X)
print("code diag", [f"{cov[i][i]:.3e}" for i in range(3)], "true diag", [f"{true[i,i]:.3e}" for i in range(3)], "ratio true/code", [round(true[i,i]/cov[i][i],1) for i in range(3)])
print("== F-S04-07 step absorbed when phase trends with time")
o=[]
for d in range(120):
    day=d; phase = 10 + 0.4*d   # phase angle trends with time
    mag = 8.0 + 0.02*phase + (0.3 if day >= 90 else 0) + rng.gauss(0,0.03)
    o.append(obs(day, mag, phase))
a = P.assess_photometry(o)
print(f"true step 0.3 mag: recovered delta {a.magnitude_change}, p={a.p_value}")
print("== F-S04-23 empty recent window")
o=[obs(d, 8.0+rng.gauss(0,0.05), 20+d%30) for d in range(60)] + [obs(150, 9.0, 25)]
o2=[x for x in o if x.epoch_utc < T0+timedelta(days=100)]
# all recent in window? make baseline only: shift windows so recent empty is hard (recent anchored to latest); instead make baseline empty
a = P.assess_photometry([obs(d, 8.0+rng.gauss(0,0.05), 20+d%30) for d in range(0, 20)], baseline_window_days=1, recent_window_days=30)
print(f"baseline window empty: p={a.p_value} conf={a.confidence} confounders={a.confounding_factors}")
print("== F-S04-21 offset epoch")
s = "2026-01-01T12:00:00+01:00"
print(s, "->", datetime.fromisoformat(s.rstrip("Z")).replace(tzinfo=UTC), "correct", datetime.fromisoformat(s).astimezone(UTC))
