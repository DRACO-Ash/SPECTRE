import sys
sys.path.insert(0, "/tmp/claude-0/-home-user-SPECTRE/e332f7aa-9fda-59a8-9619-1afe89475fea/scratchpad/tree")
from spectre.astro.pattern_of_life import parse_tle_history
g1 = ("1 25544U 98067A   24001.00000000  .00001000  00000-0  10000-3 0  9990",
      "2 25544  51.6400 100.0000 0001000  90.0000 270.0000 15.49000000 00001")
g2 = ("1 25544U 98067A   24002.00000000  .00001000  00000-0  10000-3 0  9991",
      "2 25544  51.6400  95.0000 0001000  90.0000 270.0000 15.49000000 00012")
badep = (g1[0][:18] + "XX001.00000000" + g1[0][32:], g1[1].replace("2 25544", "2 25544"))
zero_n = ("1 25544U 98067A   24003.00000000  .00001000  00000-0  10000-3 0  9992",
          "2 25544  51.6400  95.0000 0001000  90.0000 270.0000  0.00000000 00012")
for name, bad in [("bad epoch", badep), ("zero n", zero_n)]:
    txt = "\n".join([*g1, *bad, *g2])
    try:
        r = parse_tle_history(txt); print(name, "->", len(r), "records")
    except Exception as e:
        print(name, "-> raised", type(e).__name__, e)
