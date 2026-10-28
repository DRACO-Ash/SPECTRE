"""VH-379: the board page shows the forecast across lanes beside the one-lane forecast, by the guard's own rule."""
import json, os, re, shutil, subprocess, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from brain.guard import lane_paces

PAGE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", "board", "board.html"))
ACC = {"a": {"kind": "rollup", "lanes": 8, "priced": 1860, "elapsed": 280}, "b": {"kind": "release", "lanes": 4, "priced": 1000, "elapsed": 160},
       "c": {"kind": "release", "actual": 321}, "d": {"kind": "rollup", "lanes": 0, "priced": 100, "elapsed": 10},
       "e": {"kind": "item", "lanes": 2, "priced": 10, "elapsed": 5}, "f": {"kind": "release", "lanes": True, "priced": 100, "elapsed": 50}}


def page_lane_pace(rows):
    src = open(PAGE).read()
    m = re.search(r"  function lanePace\(\)\{.*?\n  \}\n", src, re.S)
    if not m:
        return "missing"
    js = f"const accuracy = {json.dumps(list(rows.values()))};\n{m.group(0)}\nconsole.log(JSON.stringify(lanePace()));"
    return json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout)


@unittest.skipUnless(shutil.which("node") and os.path.exists(PAGE), "node and the board page are needed")
class BoardPageLanes(unittest.TestCase):
    def test_the_page_counts_the_same_samples_as_the_guard_and_takes_their_median(self):
        lp = page_lane_pace(ACC)
        self.assertNotEqual(lp, "missing", "lanePace is not in board.html")
        guard = sorted(p for _, _, p in lane_paces(ACC))
        self.assertEqual(lp["n"], len(guard))
        self.assertAlmostEqual(lp["mid"], (guard[0] + guard[1]) / 2)
        self.assertTrue(lp["agree"])                                    # 0.1505 and 0.16 are within 20 percent

    def test_far_apart_samples_do_not_agree_and_none_gives_no_row(self):
        far = {"a": {"kind": "rollup", "lanes": 8, "priced": 1000, "elapsed": 150}, "b": {"kind": "release", "lanes": 6, "priced": 1000, "elapsed": 40}}
        self.assertFalse(page_lane_pace(far)["agree"])
        self.assertIsNone(page_lane_pace({"c": {"kind": "release", "actual": 1}}))

    def test_the_row_sits_beside_the_one_lane_forecast_on_store_releases_only(self):
        src = open(PAGE).read()
        self.assertIn("const lp = isRel ? lanePace() : null;", src)
        self.assertIn("Build forecast across parallel lanes", src)
        self.assertIn("not yet agreed, so the one-lane figure above stands", src)


if __name__ == "__main__":
    unittest.main()
