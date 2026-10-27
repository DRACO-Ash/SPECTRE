import sys, math
sys.path.insert(0, "/tmp/claude-0/-home-user-SPECTRE/e332f7aa-9fda-59a8-9619-1afe89475fea/scratchpad/tree")
from datetime import timedelta
from sgp4.api import Satrec, jday
from spectre.astro.pattern_of_life import _satrec_to_record, _gst_deg, _EARTH_ROT
def chk(n_revday):
    l1 = "1 99999U 20001A   26001.00000000  .00000000  00000-0  00000-0 0  9990"
    l2 = f"2 99999   0.0100  90.0000 0001000  90.0000 180.0000 {n_revday:11.8f}    15"
    # pad/ checksum not validated by sgp4 python? fix width
    l2 = l2[:68] + "0"
    rec = _satrec_to_record(l1 + "\n" + l2)
    sat = Satrec.twoline2rv(l1, l2)
    lons = []
    for d in (0.0, 10.0):
        ep = rec.epoch + timedelta(days=d)
        jd, fr = jday(ep.year, ep.month, ep.day, ep.hour, ep.minute, ep.second + ep.microsecond/1e6)
        e, r, v = sat.sgp4(jd, fr)
        lon = (math.degrees(math.atan2(r[1], r[0])) - _gst_deg(ep)) % 360
        lons.append(lon)
    true = ((lons[1]-lons[0]+180) % 360 - 180)/10.0
    print(f"n={n_revday:.8f} code drift={rec.geo_drift_rate_deg_day:+.5f} SGP4 true drift={true:+.5f} diff={rec.geo_drift_rate_deg_day-true:+.5f} deg/day")
print("_EARTH_ROT", _EARTH_ROT)
chk(_EARTH_ROT); chk(1.00273791); chk(1.0027)
