import copy, json, os, subprocess, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from brain.events import validate, apply_event, replay, read_log, save_state, EMPTY

BRAIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts", "brain.py")


def ev(**kw):
    d = {"id": "e-0001", "at": "2026-10-06T20:00:00Z", "kind": "item_state", "ref": "VH-1", "state": "built"}
    d.update(kw)
    return d


def fresh():
    return copy.deepcopy(EMPTY)


class Schema(unittest.TestCase):
    def test_a_good_event_of_each_kind_is_clean(self):
        for e in (ev(), ev(kind="accuracy", est=45, actual=6), ev(kind="gate", key="eng", status="pass"),
                  ev(kind="lanes", release="V2.8", lanes=7, priced=1860, elapsed=280)):
            if e["kind"] in ("gate", "lanes"):
                e.pop("ref", None)
            if e["kind"] != "item_state":
                e.pop("state", None)
            self.assertEqual(validate(e), [], e)

    def test_every_problem_is_listed_together(self):
        p = validate({"kind": "item_state", "state": "nonsense"})
        self.assertGreaterEqual(len(p), 4, p)            # id, at, ref, state

    def test_each_rule_can_say_both_things(self):
        self.assertTrue(validate(ev(id="x")))                       # id too short
        self.assertTrue(validate(ev(at="2026-10-06 20:00")))         # not UTC ISO
        self.assertTrue(validate(ev(kind="mystery")))
        self.assertTrue(validate(ev(kind="accuracy", ref="VH-1", est=0, actual=5)))
        self.assertTrue(validate(ev(kind="accuracy", ref="VH-1", est=True, actual=5)))   # a boolean is not a number
        self.assertTrue(validate(ev(kind="gate", key="eng", status="maybe")))
        self.assertTrue(validate("not an object"))
        self.assertEqual(validate(ev(kind="accuracy", ref="VH-1", est=5, actual=5)), [])


class Replay(unittest.TestCase):
    def test_the_same_event_twice_changes_nothing(self):
        s1, o1, _ = apply_event(fresh(), ev())
        s2, o2, _ = apply_event(s1, ev())
        self.assertEqual((o1, o2), ("applied", "duplicate"))
        self.assertEqual(s1, s2)

    def test_a_refused_event_changes_nothing_and_the_input_is_untouched(self):
        base = fresh()
        before = copy.deepcopy(base)
        s, o, why = apply_event(base, ev(state="nonsense"))
        self.assertEqual(o, "refused"); self.assertEqual(s, before); self.assertEqual(base, before); self.assertIn("state", why)

    def test_an_event_older_than_the_last_read_is_stale_and_moves_nothing(self):
        st = fresh(); st["last_read"] = "2026-10-06T21:00:00Z"
        s, o, why = apply_event(st, ev(at="2026-10-06T20:59:59Z"))
        self.assertEqual(o, "stale"); self.assertEqual(s["items"], {}); self.assertIn("last read", why)
        s2, o2, _ = apply_event(st, ev(id="e-0002", at="2026-10-06T21:00:00Z"))
        self.assertEqual(o2, "applied")                        # an event at the read time itself is not late

    def test_a_replayed_log_does_not_call_applied_events_stale(self):
        log = json.dumps(ev()) + "\n"
        s, r1 = replay(None, log, "2026-10-06T21:00:00Z")
        self.assertEqual(s["last_read"], "2026-10-06T21:00:00Z")      # a replay records when the board read the log
        s, r2 = replay(s, log, "2026-10-06T22:00:00Z")
        self.assertEqual((r1["applied"], r2["applied"], r2["duplicate"], r2["stale"]), (1, 0, 1, 0))

    def test_a_bad_line_is_reported_with_its_number_and_the_rest_still_apply(self):
        log = json.dumps(ev(id="e-0001")) + "\n{broken\n" + json.dumps(ev(id="e-0002", ref="VH-2")) + "\n" + json.dumps(ev(id="e-0003", state="zzz")) + "\n"
        s, r = replay(None, log, "2026-10-06T21:00:00Z")
        self.assertEqual((r["applied"], r["refused"]), (2, 1))
        self.assertTrue(any(p.startswith("line 2: not JSON") for p in r["problems"]), r["problems"])
        self.assertTrue(any(p.startswith("line 4: refused") for p in r["problems"]), r["problems"])
        self.assertEqual(sorted(s["items"]), ["VH-1", "VH-2"])

    def test_each_kind_lands_where_it_belongs(self):
        s = fresh()
        for e in (ev(), ev(id="e-0002", kind="accuracy", ref="VH-1", est=45, actual=6),
                  ev(id="e-0003", kind="gate", key="eng", status="pass"), ev(id="e-0004", kind="lanes", release="V2.8", lanes=7, priced=1860, elapsed=280)):
            s, o, _ = apply_event(s, e)
            self.assertEqual(o, "applied")
        self.assertEqual((s["items"]["VH-1"]["state"], s["accuracy"][0]["actual"], s["gates"]["eng"]["status"], s["lanes"]["V2.8"]["lanes"]), ("built", 6, "pass", 7))


class Writing(unittest.TestCase):
    def test_a_failed_write_leaves_the_old_file_whole(self):
        d = tempfile.mkdtemp(); p = os.path.join(d, "state.json")
        save_state(p, {"a": 1})
        with self.assertRaises(TypeError):
            save_state(p, {"a": object()})
        self.assertEqual(json.load(open(p)), {"a": 1})
        self.assertEqual([f for f in os.listdir(d) if f.endswith(".tmp")], [])


class Command(unittest.TestCase):
    def run_cli(self, log, state, *extra):
        return subprocess.run([sys.executable, BRAIN, "events", "--log", log, "--state", state, "--now", "2026-10-06T21:00:00Z", *extra], capture_output=True, text=True)

    def test_dry_run_writes_nothing_and_write_writes(self):
        d = tempfile.mkdtemp(); log = os.path.join(d, "e.jsonl"); st = os.path.join(d, "s.json")
        open(log, "w").write(json.dumps(ev()) + "\n")
        r = self.run_cli(log, st)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr); self.assertIn("dry run", r.stdout); self.assertFalse(os.path.exists(st))
        r = self.run_cli(log, st, "--write")
        self.assertEqual(r.returncode, 0); self.assertEqual(json.load(open(st))["items"]["VH-1"]["state"], "built")

    def test_a_problem_makes_it_exit_one(self):
        d = tempfile.mkdtemp(); log = os.path.join(d, "e.jsonl"); st = os.path.join(d, "s.json")
        open(log, "w").write("{broken\n")
        r = self.run_cli(log, st)
        self.assertEqual(r.returncode, 1); self.assertIn("line 1", r.stdout)

    def test_a_bad_now_is_refused(self):
        d = tempfile.mkdtemp(); log = os.path.join(d, "e.jsonl"); open(log, "w").write("")
        r = subprocess.run([sys.executable, BRAIN, "events", "--log", log, "--state", os.path.join(d, "s.json"), "--now", "yesterday"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
