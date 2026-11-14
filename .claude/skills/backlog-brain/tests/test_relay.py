import datetime, json, os, re, shutil, subprocess, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from brain.relay import check, targets, poke_requests, session_of, stamp

BRAIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts", "brain.py")
NOW = datetime.datetime(2026, 10, 6, 20, 30, tzinfo=datetime.timezone.utc)
S1, S2, S3, S4 = ("session_" + c * 24 for c in "ABCD")
TH = {"b": {"name": "Backlog", "role": "backlog", "sessionId": S1, "order": 1},
      "d1": {"name": "Development 1", "role": "development", "url": "https://claude.ai/code/" + S2, "order": 6},
      "d2": {"name": "Development 2", "role": "development", "sessionId": S3, "order": 4},
      "d3": {"name": "Development 3", "role": "development", "sessionId": "not-a-session", "order": 5}}
LK = {"1": {"from": "b", "kind": "feeds work to", "to": "d2"}, "2": {"from": "b", "kind": "feeds work to", "to": "d1"},
      "3": {"from": "b", "kind": "feeds work to", "to": "d3"}, "4": {"from": "d1", "kind": "is the prime development thread for", "to": "d2"},
      "5": {"from": "b", "kind": "feeds work to", "to": "ghost"}, "6": {"from": "b", "kind": "feeds work to", "to": "d1"}}


class Bound(unittest.TestCase):
    def test_a_registered_thread_with_a_session_is_reachable(self):
        self.assertEqual(check(TH, "b", "d1"), S2)       # the id is read from the url when there is no sessionId

    def test_each_refusal_can_fire(self):
        for src, dst, kind, text in (("b", "b", "poke", "itself"), ("b", "ghost", "poke", "registered"), ("ghost", "d1", "poke", "registered"),
                                     ("b", "d3", "poke", "no valid session"), ("b", "d1", "delete", "not covered")):
            with self.assertRaises(ValueError) as cm:
                check(TH, src, dst, kind)
            self.assertIn(text, str(cm.exception))
        noself = {"b": {"name": "B"}, "d1": TH["d1"]}
        with self.assertRaises(ValueError):
            check(noself, "b", "d1")                       # a sender with no session is not covered either

    def test_a_malformed_session_id_is_not_one(self):
        self.assertEqual(session_of({"sessionId": "session_x"}), "")
        self.assertEqual(session_of({"url": "https://claude.ai/code/" + S4}), S4)


class Targets(unittest.TestCase):
    def test_targets_follow_the_relationship_in_board_order_without_repeats_or_ghosts(self):
        self.assertEqual(targets(TH, LK, "b", "feeds work to"), ["d2", "d3", "d1"])      # the board's order, not the alphabet
        self.assertEqual(targets(TH, LK, "d1", "is the prime development thread for"), ["d2"])
        self.assertEqual(targets(TH, LK, "d2", "feeds work to"), [])


class Requests(unittest.TestCase):
    def test_requests_carry_the_target_session_and_the_clock_stamp(self):
        reqs, owner = poke_requests(TH, LK, "b", "feeds work to", " hold the freeze ", NOW)
        self.assertEqual([r["to"] for r in reqs], ["d2", "d1"])
        a = reqs[1]["arguments"]
        self.assertEqual(a["persistent_session_id"], S2)
        self.assertTrue(a["prompt"].startswith("From the Backlog thread, 20:30 UTC 2026-10-06. hold the freeze"), a["prompt"])
        self.assertEqual([o["to"] for o in owner], ["d3"])                   # the thread with no valid session goes to the owner, unsent

    def test_the_time_is_the_clock_and_never_the_caller(self):
        self.assertEqual(stamp(NOW), "20:30 UTC 2026-10-06")
        reqs, _ = poke_requests(TH, LK, "b", "feeds work to", "x")           # no clock given: now, in UTC
        m = re.match(r"^From the Backlog thread, (\d\d:\d\d) UTC (\d{4}-\d\d-\d\d)\. x$", reqs[0]["arguments"]["prompt"])
        self.assertTrue(m, reqs[0]["arguments"]["prompt"])
        real = datetime.datetime.now(datetime.timezone.utc)
        stamped = datetime.datetime.strptime(m.group(2) + " " + m.group(1), "%Y-%m-%d %H:%M").replace(tzinfo=datetime.timezone.utc)
        self.assertLess(abs((real - stamped).total_seconds()), 120)           # it is the clock, within two minutes

    def test_no_link_and_no_message_are_refused(self):
        reqs, owner = poke_requests(TH, LK, "d2", "feeds work to", "x", NOW)
        self.assertEqual(reqs, []); self.assertIn("no 'feeds work to' link", owner[0]["why"])
        with self.assertRaises(ValueError):
            poke_requests(TH, LK, "b", "feeds work to", "   ")
        with self.assertRaises(ValueError):
            poke_requests(TH, LK, "ghost", "feeds work to", "x")


class Command(unittest.TestCase):
    def dirs(self):
        d = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, d, True)
        for name, data in (("threads", TH), ("links", LK)):
            os.makedirs(os.path.join(d, name))
            for k, v in data.items():
                json.dump({"data": v}, open(os.path.join(d, name, k + ".json"), "w"))
        return os.path.join(d, "threads"), os.path.join(d, "links")

    def test_it_prints_requests_and_says_what_needs_the_owner(self):
        t, l = self.dirs()
        r = subprocess.run([sys.executable, BRAIN, "relay", "--threads", t, "--links", l, "--from", "b", "--relation", "feeds work to", "--message", "hello"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(len(out["requests"]), 2); self.assertEqual(out["needs_owner"][0]["to"], "d3"); self.assertEqual([x["to"] for x in out["requests"]], ["d2", "d1"])

    def test_nothing_sendable_exits_two(self):
        t, l = self.dirs()
        r = subprocess.run([sys.executable, BRAIN, "relay", "--threads", t, "--links", l, "--from", "d2", "--relation", "feeds work to", "--message", "hello"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)

    def test_to_checks_one_poke_against_the_standing_approval(self):
        # relay_check.py retired into this (VH-584): the target session on stdout, or exit 2 with the reason
        t, _ = self.dirs()
        run = lambda *x: subprocess.run([sys.executable, BRAIN, "relay", "--threads", t, "--from", "b", *x], capture_output=True, text=True)
        ok = run("--to", "d2")
        self.assertEqual((ok.returncode, ok.stdout.strip()), (0, TH["d2"]["sessionId"]))
        for args in (("--to", "ghost"), ("--to", "d3"), ("--to", "d2", "--kind", "delete"), ("--to", "b")):
            no = run(*args)
            self.assertEqual(no.returncode, 2, args); self.assertIn("needs the owner", no.stderr)
        self.assertEqual(run().returncode, 2)                    # neither --to nor the three a relay needs


if __name__ == "__main__":
    unittest.main()
