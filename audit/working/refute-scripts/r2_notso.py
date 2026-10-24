import sys
sys.path.insert(0, "/tmp/claude-0/-home-user-SPECTRE/e332f7aa-9fda-59a8-9619-1afe89475fea/scratchpad/tree")
from datetime import datetime, timedelta, UTC
from types import SimpleNamespace as NS
from spectre.astro import notso as N
P = N.parse_notso_text
print("== S03-07 dedicated DV field")
for t in ["SATNO: 43689\nEFFECTIVE START: 2025-03-14T12:00:00Z\nPREDICTED DV: 1.5 m/s",
          "SATNO: 43689\nEFFECTIVE START: 2025-03-14T12:00:00Z\nDELTA-V: 0.005 km/s",
          "SATNO: 43689\nEFFECTIVE START: 2025-03-14T12:00:00Z\nDESCRIPTION: delta-v 1.5 m/s burn"]:
    r = P(t); print(repr(t.splitlines()[-1]), "->", [x.predicted_delta_v_km_s for x in r])
print("== S03-08 fallbacks / fractional seconds")
print(N._parse_dt("2025-03-14T12:00:00.123Z"), N._parse_dt("2025-03-14T12:00:00+00:00"))
r = P("SATNO: 43689\nTYPE: manoeuvre"); print("no dates ->", r[0].issue_date_utc, r[0].effective_start_utc, r[0].effective_end_utc)
r = P("SATNO: 43689\nISSUE DATE: 2025-03-10T00:00:00Z\nEFFECTIVE START: 2025-03-14T12:00:00.5Z\nEFFECTIVE END: 2025-03-14T18:00:00.5Z")
print("frac secs window ->", r[0].effective_start_utc, r[0].effective_end_utc)
print("== S03-09 MSGID mid-message")
t = "SATNO: 43689\nMSGID: X\nEFFECTIVE START: 2025-03-14T12:00:00Z\nEFFECTIVE END: 2025-03-15T12:00:00Z\nTYPE: manoeuvre"
print("split:", N._split_messages(t))
r = P(t); print("records:", [(x.message_id, x.norad_id, x.effective_start_utc, x.effective_end_utc) for x in r])
print("== S03-10 dropped silently")
import logging; logging.basicConfig(level=logging.WARNING)
r = P("SATNO: 43689\nEFFECTIVE START: 2025-03-14T12:00:00Z\n---\nTYPE: manoeuvre\nEFFECTIVE START: 2025-03-15T12:00:00Z")
print("2 msgs ->", len(r), "records")
print("== S03-11 bare 5-digit fallback")
r = P("OPERATOR: ACME\nTYPE: proximity ops close approach with 43013\nEFFECTIVE START: 2025-03-14T12:00:00Z")
print("->", [x.norad_id for x in r])
print("== S03-26 slash date")
print(N._parse_dt("03/04/2026 12:00"), N._parse_dt("141200Z MAR 25"))
print("== S03-31 keyword")
print(N._infer_notso_type("latest manoeuvre plan"), N._infer_notso_type("follower spacecraft"))
print("== S03-12 lead time sign, S03-13 greedy")
base = datetime(2025,3,14,12,tzinfo=UTC)
def man(ep, dv=0.001): return NS(epoch=ep, delta_v_km_s=dv, tle_after=NS(sma_km=7000.0))
def rec(mid, s, e, issue): return N.NOTSORecord(message_id=mid, norad_id=1, international_designator=None, object_name=None, issuing_entity="X", issue_date_utc=issue, effective_start_utc=s, effective_end_utc=e, notso_type=N.NOTSOType.MANOEUVRE, description="", predicted_delta_v_km_s=None, predicted_direction=None, raw_message="")
c = N.correlate_notsos_with_manoeuvres([rec("A", base-timedelta(hours=2), base+timedelta(hours=4), base-timedelta(days=3))], [man(base)], 1)
print("lead time (issued 3 d ahead, window opens 2 h before burn):", c[0].time_offset_hours)
# greedy: NOTSO A window [0,6h], NOTSO B window [20h,26h]; manoeuvres at 21h and 40h? construct mis-assignment
A = rec("A", base, base+timedelta(hours=6), base); B = rec("B", base+timedelta(hours=20), base+timedelta(hours=26), base)
m1 = man(base+timedelta(hours=22)); m2 = man(base-timedelta(hours=20))
c = N.correlate_notsos_with_manoeuvres([A,B],[m1,m2],1)
print("greedy:", [(x.notso.message_id if x.notso else None, x.correlation_type, x.manoeuvre.epoch if x.manoeuvre else None) for x in c])
print("== S03-02 burn_epoch ignored: after-set epoch 3 d after burn inside window")
c = N.correlate_notsos_with_manoeuvres([rec("A", base, base+timedelta(hours=24), base-timedelta(days=1))], [man(base+timedelta(days=3))], 1)
print([x.correlation_type for x in c])
