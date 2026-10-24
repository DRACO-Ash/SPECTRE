from sgp4.api import Satrec
for inc, n in ((0.01, 15.5), (51.64, 15.5), (97.6, 14.8)):
    l1 = "1 25544U 98067A   24001.00000000  .00001000  00000-0  10000-3 0  9990"
    l2 = f"2 25544 {inc:8.4f} 100.0000 0001000  90.0000 270.0000 {n:11.8f} 00001"
    s = Satrec.twoline2rv(l1, l2)
    aK = (398600.4418/((s.no_kozai/60)**2))**(1/3); aB = s.a*6378.135
    print(inc, "a_kozai_wgs84", round(aK,3), "a_unkozai_wgs72", round(aB,3), "diff km", round(aK-aB,3))
