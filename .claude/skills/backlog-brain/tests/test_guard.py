import datetime, os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from brain.guard import check

PLAN = {"r-a": {"name": "R1.0"}, "r-b": {"name": "R1.1"}, "r-old": {"name": "R0.9", "status": "released"}}
NOW = datetime.datetime(2026, 10, 6, 20, 0, tzinfo=datetime.timezone.utc)
CFG = {"releases": {"cap_min": 100}, "guard": {"release_regex": r"\bR\d+\.\d+\b"}}
DEC = {"question": "q", "options": [{"label": "a"}]}


def it(**kw):
    d = {"state": "open", "release": "r-a", "minutes": 30, "note": "", "time": "30m"}
    d.update(kw)
    return d


class Guard(unittest.TestCase):
    def run_check(self, items, **kw):
        return check(items, PLAN, kw.pop("cfg", CFG), **kw)

    def test_a_clean_board_is_clean_and_rows_are_counted(self):
        f, w, rows = self.run_check({"T-1": it(), "T-2": it(release="r-b", minutes=10, time="10m")})
        self.assertEqual((f, w), ([], [])); self.assertEqual(rows, {"R1.0": [1, 30], "R1.1": [1, 10]})

    def test_a_stale_dump_fails_and_a_fresh_one_does_not(self):
        self.assertIn("STALE DUMP", " ".join(self.run_check({"T-1": it()}, dump_age_min=16)[0]))
        self.assertEqual(self.run_check({"T-1": it()}, dump_age_min=15)[0], [])

    def test_the_limit_comes_from_the_settings(self):
        c = {"guard": {"max_dump_age_min": 60}}
        self.assertEqual(self.run_check({"T-1": it()}, cfg=c, dump_age_min=59)[0], [])

    def test_a_note_placing_the_task_elsewhere_fails_using_the_projects_own_release_names(self):
        f, _, _ = self.run_check({"T-1": it(note="it was moved to R1.1 last week")})
        self.assertEqual(len(f), 1); self.assertIn("release field is R1.0", f[0])
        self.assertEqual(self.run_check({"T-1": it(note="it was moved to R1.0 last week")})[0], [])        # the note agrees: clean
        self.assertEqual(self.run_check({"T-1": it(note="if it fails it moves to R1.1")})[0], [])           # a conditional is not a claim

    def test_a_time_field_that_disagrees_with_the_minutes_fails(self):
        self.assertIn("time field starts 45m", self.run_check({"T-1": it(time="45m: x")})[0][0])

    def test_an_umbrella_with_minutes_beside_its_children_fails(self):
        f, _, _ = self.run_check({"T-1": it(note="This is the UMBRELLA"), "T-1-A": it(parent="T-1")})
        self.assertEqual(len(f), 1); self.assertIn("umbrella", f[0])

    def test_a_decision_nobody_can_see_fails_until_it_is_answered_or_surfaced(self):
        self.assertIn("unanswered decision", self.run_check({"T-1": it(decision=DEC)})[0][0])
        self.assertEqual(self.run_check({"T-1": it(decision=DEC, state="input")})[0], [])
        self.assertEqual(self.run_check({"T-1": it(decision=DEC, decisionAnswer={"label": "a"})})[0], [])

    def test_a_closed_task_in_a_live_release_fails_a_built_one_only_warns(self):
        f, w, _ = self.run_check({"T-1": it(state="closed"), "T-2": it(state="built")})
        self.assertEqual(len(f), 1); self.assertIn("T-1", f[0]); self.assertEqual(len(w), 1); self.assertIn("T-2", w[0])
        self.assertEqual(self.run_check({"T-1": it(state="closed", release="r-old")})[0], [])

    def test_a_release_over_its_cap_only_warns(self):
        f, w, _ = self.run_check({"T-1": it(minutes=150, time="150m")})
        self.assertEqual(f, []); self.assertIn("ADVISORY", w[0])
        self.assertEqual(self.run_check({"T-1": it(minutes=150, time="150m")}, cfg={})[1], [])        # no cap set, no warning

    def test_a_stale_header_fails_a_paused_board_does_not(self):
        old = {"updatedAt": "2026-10-06T17:00:00Z"}
        self.assertIn("HEADER STALE", self.run_check({"T-1": it()}, meta=old, now=NOW)[0][0])
        self.assertEqual(self.run_check({"T-1": it()}, meta={"updatedAt": "2026-10-06T19:30:00Z"}, now=NOW)[0], [])
        f, w, _ = self.run_check({"T-1": it()}, meta=dict(old, syncPaused=True, pausedAt="x", idleChecks=3), now=NOW)
        self.assertEqual(f, []); self.assertIn("PAUSED", w[0])


if __name__ == "__main__":
    unittest.main()
