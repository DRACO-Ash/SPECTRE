import sys
sys.path.insert(0, "/tmp/claude-0/-home-user-SPECTRE/e332f7aa-9fda-59a8-9619-1afe89475fea/scratchpad/tree")
from datetime import datetime, UTC
from spectre.domain.decision import *
ep = datetime(2025,6,1,tzinfo=UTC)
# 1. Hand matrix: rows adversaries, cols A,B. A=(0.9,0.1) B=(0.5,0.5)
def om(x): return OutcomeMetrics(True,0,0,0,0,x)
adv=[AdversaryAction("a1","a1",ActionType.MANOEUVRE,0.5,0.5),AdversaryAction("a2","a2",ActionType.NO_ACTION,0.5,0.5)]
fr=[FriendlyResponse("A","A",ActionType.MANOEUVRE,0,0,0),FriendlyResponse("B","B",ActionType.MANOEUVRE,0,0,0)]
s=Scenario("t",ep,adv,fr)
M=[[om(0.9),om(0.5)],[om(0.1),om(0.5)]]
for st in SelectorStrategy: print("hand", st.value, find_robust_response(s,M,st).id)
# 2. test fixture
def _adv(id,atype,prob=0.6,conf=0.8): return AdversaryAction(id,"x",atype,prob,conf)
def _fr(id,atype,cost=0.3,rev=0.8,time_h=6.0): return FriendlyResponse(id,id,atype,cost,rev,time_h)
a1=_adv("A1",ActionType.MANOEUVRE); a2=_adv("A2",ActionType.NO_ACTION)
r1=_fr("R1",ActionType.MANOEUVRE,0.4,0.7); r2=_fr("R2",ActionType.SENSOR_RETASK,0.1,0.9); r3=_fr("R3",ActionType.NO_ACTION,0.0,1.0)
s=Scenario("t",ep,[a1,a2],[r1,r2,r3],horizon_hours=72.0)
M=[[compute_outcome_metrics(a,r,s) for r in [r1,r2,r3]] for a in [a1,a2]]
for i,row in enumerate(M):
    for j,m in enumerate(row): print("fixture",i,j,m.custody_maintained,m.custody_gap_hours,m.closest_approach_km,m.composite_score)
for j in range(3): print("worst",j,max(M[i][j].composite_score for i in range(2)))
for st in SelectorStrategy: print("fixture", st.value, find_robust_response(s,M,st).id)
# 3. custody: NO_ACTION rev 1.0 vs rev 0.0 against manoeuvre
for rev in (1.0,0.5,0.0):
    m=compute_outcome_metrics(a1,_fr("N",ActionType.NO_ACTION,0,rev,6),s); print("noaction rev",rev,m.custody_maintained,m.custody_gap_hours,m.composite_score)
# POSTURE_CHANGE friendly custody
m=compute_outcome_metrics(a1,_fr("P",ActionType.POSTURE_CHANGE,0.3,0.5),s); print("posture",m.custody_maintained,m.custody_gap_hours)
# 4. validation: horizon 0, rev>1, negative
try:
    compute_outcome_metrics(a1,r1,Scenario("t",ep,[a1],[r1],horizon_hours=0.0))
except Exception as e: print("h0",type(e).__name__,e)
m=compute_outcome_metrics(a1,_fr("N",ActionType.NO_ACTION,0,1.5),s); print("rev1.5",m.custody_gap_hours,m.composite_score)
m=compute_outcome_metrics(a1,_fr("N",ActionType.MANOEUVRE,-2,0.5),s); print("cost-2",m.closest_approach_km,m.delta_v_cost_km_s,m.composite_score)
# 5. TLE path with bad TLE silently swallowed
m=compute_outcome_metrics(a1,r1,s,blue_tle="garbage",red_tle="garbage"); print("badtle",m.closest_approach_km)
