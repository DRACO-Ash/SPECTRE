import sys
sys.path.insert(0, "/tmp/claude-0/-home-user-SPECTRE/e332f7aa-9fda-59a8-9619-1afe89475fea/scratchpad/tree")
from spectre.domain.manoeuvre_calibration import *
for v in (float("nan"), -1.0, float("inf")):
    p = classify_posture(v, "GEO", ManoeuvreKind.PHASING); print(v, p.posture, getattr(p,"rationale","")[:90])
print(kind_for_method("geo_drift"), kind_for_method("evasion"))
