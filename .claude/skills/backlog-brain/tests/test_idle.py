"""The hourly sync's idle check, which moved into the pack as brain/idle.py (VH-584): its own self-test, and the command."""
import contextlib, io, json, os, shutil, subprocess, sys, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
from brain.idle import COLLECTIONS, selftest  # noqa: E402

BRAIN = os.path.join(HERE, "..", "scripts", "brain.py")


class Idle(unittest.TestCase):
    def test_the_rules_hold(self):
        with contextlib.redirect_stdout(io.StringIO()):
            selftest()     # bookkeeping ignored, four kinds of change seen, incomplete reads refused, a pause on the third quiet check

    def dump(self, items=True):
        d = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, d, True)
        for c in COLLECTIONS:
            os.makedirs(os.path.join(d, c))
        docs = {"plan": {"r": {"name": "V1.0"}}, "items": {"PRJ-1": {"minutes": 5}} if items else {}}
        for c, kv in docs.items():
            for k, v in kv.items():
                json.dump({"data": v}, open(os.path.join(d, c, k + ".json"), "w"))
        os.makedirs(os.path.join(d, "board")); json.dump({"data": {"currentRelease": "V1.0"}}, open(os.path.join(d, "board", "meta.json"), "w"))
        return d

    def test_the_command_counts_a_quiet_check_and_refuses_an_incomplete_read(self):
        d = self.dump()
        run = lambda dump, meta: subprocess.run([sys.executable, BRAIN, "idle", "--dump", dump, "--sha", "abc", "--meta", meta,
                                                 "--now", "2026-10-07T11:00:00Z"], capture_output=True, text=True)
        first = run(d, os.path.join(d, "board", "meta.json"))
        self.assertEqual(first.returncode, 0, first.stderr)
        r = json.loads(first.stdout); self.assertTrue(r["changed"])                     # no baseline yet is a change
        meta = os.path.join(d, "m2.json"); json.dump({"currentRelease": "V1.0", "syncFingerprint": r["fingerprint"], "idleChecks": 2}, open(meta, "w"))   # the same header, with the bookkeeping
        third = json.loads(run(d, meta).stdout)
        self.assertEqual((third["changed"], third["idleChecks"], third["pause"]), (False, 3, True))
        empty = self.dump(items=False)
        bad = run(empty, os.path.join(empty, "board", "meta.json"))
        self.assertEqual(bad.returncode, 2); self.assertFalse(json.loads(bad.stdout)["pause"])   # a board with no items never pauses


if __name__ == "__main__":
    unittest.main()
