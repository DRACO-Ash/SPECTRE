import datetime, os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from brain.guard import (check_intake, check_threads, overhead_warnings, lane_paces, lane_lines, table, write_block, document_only, BEGIN, END)

CFG = {"releases": {"pace": 0.33, "overhead_min": 375, "cap_min": 1409}, "guard": {"release_regex": r"\bV\d+\.\d+\b"}}
NOW = datetime.datetime(2026, 10, 1, 19, 0, tzinfo=datetime.timezone.utc)
ITEMS = {"VH-20": {"note": "Owner intake aaaa1111bbbb2222cccc, 2026-09-29. VALID.", "task": "t"}, "VH-21": {"note": "", "task": "t"}}
FEEDS, RAISES = "feeds work to", "passes back tasks it cannot solve in the current release to"
MASTER, GLOVE, INSTRUCTS, PASSES = "is the prime development thread for", "works hand in glove with", "instructs", "passes tasks to"


def intake_one(**kw):
    base = {"status": "submitted", "submittedAt": "2026-10-01T18:30:00Z", "title": "x"}
    base.update(kw)
    return " ".join(check_intake({"eeee1111bbbb2222cccc": base}, ITEMS, NOW, CFG))


class Intake(unittest.TestCase):
    def test_clean_entries_are_clean(self):
        ok = {"aaaa1111bbbb2222cccc": {"status": "logged", "ref": "VH-20", "resolvedAt": "2026-09-29T03:00:00Z", "outcome": "Valid, logged as VH-20.", "title": "x"},
              "dddd1111bbbb2222cccc": {"status": "submitted", "submittedAt": "2026-10-01T18:30:00Z", "title": "fresh"}}
        self.assertEqual(check_intake(ok, ITEMS, NOW, CFG), [])

    def test_every_planted_fault_is_caught(self):
        self.assertIn("waiting", intake_one(submittedAt="2026-09-29T02:14:24Z"))
        self.assertIn("already actioned", intake_one(ref="VH-20"))
        self.assertIn("already actioned", " ".join(check_intake({"aaaa1111bbbb2222cccc": {"status": "submitted", "submittedAt": "2026-10-01T18:30:00Z", "title": "x"}}, ITEMS, NOW, CFG)))
        self.assertIn("not submitted", intake_one(status="done"))
        self.assertIn("no resolvedAt", intake_one(status="logged", ref="VH-20"))
        self.assertIn("no ref", intake_one(status="logged", resolvedAt="z"))
        self.assertIn("not on the board", intake_one(status="logged", ref="VH-99", resolvedAt="z"))
        self.assertIn("no outcome", intake_one(status="rejected", resolvedAt="z"))
        self.assertIn("names a release", intake_one(status="rejected", resolvedAt="z", outcome="Logged in V2.8"))

    def test_the_wait_limit_comes_from_the_settings(self):
        c = dict(CFG, guard=dict(CFG["guard"], intake_max_min=600))
        x = {"eeee1111bbbb2222cccc": {"status": "submitted", "submittedAt": "2026-10-01T12:00:00Z", "title": "x"}}
        self.assertEqual(check_intake(x, ITEMS, NOW, c), [])
        self.assertIn("waiting", " ".join(check_intake(x, ITEMS, NOW, CFG)))


TH = {"b": {"role": "backlog", "name": "B"}, "d1": {"role": "development", "name": "D1", "order": 2}, "d2": {"role": "development", "name": "D2", "order": 4},
      "d3": {"role": "development", "name": "D3", "order": 5}, "doc": {"role": "documentation", "name": "Doc"}}


def full_links():
    full = {}
    def add(f, k, t):
        full[f"{f}-{t}-{k}"] = {"from": f, "kind": k, "to": t}
    for d in ("d1", "d2", "d3"):
        add("b", FEEDS, d); add(d, RAISES, "b")
    for d in ("d2", "d3"):
        add("d1", MASTER, d); add(d, GLOVE, "d1")
    add("d1", INSTRUCTS, "doc"); add("doc", PASSES, "b")
    return full


class Threads(unittest.TestCase):
    def without(self, kind, f=None, t=None):
        return {k: v for k, v in full_links().items() if not (v["kind"] == kind and (f is None or v["from"] == f) and (t is None or v["to"] == t))}

    def said(self, links):
        return " ".join(check_threads(TH, links, CFG))

    def test_any_number_of_development_threads_is_clean(self):
        self.assertEqual(check_threads(TH, full_links(), CFG), [])

    def test_every_missing_link_is_named(self):
        self.assertIn("D3: Backlog does not feed", self.said(self.without(FEEDS, "b", "d3")))
        self.assertIn("D2: it has no way to pass back", self.said(self.without(RAISES, "d2")))
        self.assertIn("prime development thread", self.said(self.without(MASTER, "d1", "d3")))
        self.assertIn("hand in glove", self.said(self.without(GLOVE, "d2")))
        self.assertIn("does not instruct", self.said(self.without(INSTRUCTS)))
        self.assertIn("cannot pass tasks", self.said(self.without(PASSES)))

    def test_a_dangling_link_two_primes_and_a_wrong_prime_are_caught(self):
        self.assertIn("not a thread", self.said(dict(full_links(), x={"from": "ghost", "kind": FEEDS, "to": "b"})))
        two = dict(full_links(), m2={"from": "d2", "kind": MASTER, "to": "d3"})
        self.assertIn("exactly one prime development thread", self.said(two))
        wrong = {k: v for k, v in full_links().items() if v["kind"] not in (MASTER, GLOVE)}
        wrong.update(m={"from": "d2", "kind": MASTER, "to": "d1"}, m2={"from": "d2", "kind": MASTER, "to": "d3"},
                     g1={"from": "d1", "kind": GLOVE, "to": "d2"}, g3={"from": "d3", "kind": GLOVE, "to": "d2"})
        self.assertIn("Development 1 is always the prime", self.said(wrong))

    def test_the_relation_words_come_from_the_settings(self):
        c = {"guard": {"relations": {"feeds": "briefs"}}}
        self.assertIn("Backlog does not feed", " ".join(check_threads(TH, full_links(), c)))


class Forecast(unittest.TestCase):
    def test_overhead_warns_only_for_a_store_release_whose_build_is_smaller(self):
        ow = overhead_warnings({"V2.7": (4, 1377), "V2.8": (3, 1055), "Unassigned": (2, 195), "Brain": (1, 100)}, {"Brain"}, CFG)
        self.assertEqual(len(ow), 1); self.assertTrue(ow[0].startswith("V2.8")); self.assertIn("outweighs", ow[0])
        self.assertEqual(overhead_warnings({"V2.7": (4, 1377)}, set(), CFG), [])

    ACC = {"a": {"kind": "rollup", "lanes": 8, "priced": 1860, "elapsed": 280}, "b": {"kind": "release", "lanes": 4, "priced": 1000, "elapsed": 160},
           "c": {"kind": "release", "actual": 321}, "d": {"kind": "rollup", "lanes": 0, "priced": 100, "elapsed": 10},
           "e": {"kind": "item", "lanes": 2, "priced": 10, "elapsed": 5}, "f": {"kind": "release", "lanes": True, "priced": 100, "elapsed": 50}}

    def test_only_complete_release_or_rollup_rows_are_samples(self):
        self.assertEqual([k for k, _, _ in lane_paces(self.ACC)], ["a", "b"])

    def test_two_close_samples_agree_one_or_far_apart_do_not_and_tooling_gets_no_line(self):
        sm = lane_paces(self.ACC)
        ll = lane_lines({"V2.8": (3, 1000), "Brain": (1, 100), "Unassigned": (2, 5)}, sm, {"Brain"}, CFG)
        self.assertIn("they agree", ll[0]); self.assertNotIn("not yet agreed", ll[0])
        self.assertEqual(len(ll), 2); self.assertTrue(ll[1].startswith("LANE PACE V2.8"))
        self.assertIn("not yet agreed", lane_lines({"V2.8": (3, 1000)}, sm[:1], (), CFG)[0])
        self.assertIn("not yet agreed", lane_lines({"V2.8": (3, 1000)}, [("a", 8, 0.15), ("b", 4, 0.40)], (), CFG)[0])
        self.assertIn("no release row", lane_lines({}, [], (), CFG)[0])

    def test_the_table_uses_the_projects_pace_and_overhead(self):
        t = table({"V2.8": (3, 1000), "Brain": (1, 100), "Unassigned": (2, 5)}, {"Brain"}, CFG)
        self.assertIn("| V2.8 | 3 | 1000 | 11h45 |", t)                  # 1000 x 0.33 + 375 = 705 minutes
        self.assertIn("| Brain | 1 | 100 | 0h33 build, no store upload |", t)
        self.assertIn("| Unassigned | 2 | 5 | off the release path |", t)

    def test_a_release_holding_only_research_or_document_items_is_charged_no_store_overhead(self):
        # VH-468: a research or document item ships no store artefact, so a release of nothing else pays no release overhead.
        plan = {"r-a": {"name": "V2.14"}, "r-b": {"name": "V2.8"}, "r-c": {"name": "V2.9"}}
        items = {"D-1": {"state": "open", "release": "r-a", "kind": "research", "minutes": 800},
                 "D-2": {"state": "open", "release": "r-a", "kind": "document", "minutes": 480},
                 "D-3": {"state": "built", "release": "r-b", "kind": "document", "minutes": 50},
                 "C-1": {"state": "open", "release": "r-b", "minutes": 100},
                 "D-4": {"state": "open", "release": "r-b", "kind": "investigation", "minutes": 60},
                 "C-2": {"state": "open", "release": "r-c", "minutes": 10}}
        self.assertEqual(document_only(items, plan), {"V2.14"})
        self.assertEqual(document_only({}, plan), set())
        self.assertEqual(document_only({"C-9": {"state": "open", "release": "r-c", "kind": "build", "minutes": 5}}, plan), set())


class StateBlock(unittest.TestCase):
    def test_the_block_is_replaced_in_place_and_inserted_when_absent(self):
        d = tempfile.mkdtemp(); p = os.path.join(d, "B.md")
        open(p, "w").write("# Backlog\n\nintro\n")
        write_block(p, {"V1": (1, 10)}, "2026-10-06 22:00 UTC", "x", (), CFG)
        s = open(p).read()
        self.assertEqual((s.count(BEGIN), s.count(END)), (1, 1)); self.assertIn("intro", s)
        write_block(p, {"V1": (2, 20)}, "2026-10-06 23:00 UTC", "y", (), CFG)
        s = open(p).read()
        self.assertEqual((s.count(BEGIN), s.count(END)), (1, 1)); self.assertIn("23:00", s); self.assertNotIn("22:00", s); self.assertIn("intro", s)


def write_dump(root, items, plan, **extra):
    import json
    cols = dict(items=items, plan=plan, **extra)
    for name, docs in cols.items():
        os.makedirs(os.path.join(root, name), exist_ok=True)
        for k, v in docs.items():
            json.dump(v, open(os.path.join(root, name, k + ".json"), "w"))


class CheckCommand(unittest.TestCase):
    """The command reads intake, threads, links and accuracy from the same dump, and writes the state block only from a fresh read."""
    def run_cmd(self, dump, *more):
        import json, subprocess
        cfg = os.path.join(dump, "cfg.json"); json.dump(CFG, open(cfg, "w"))
        r = subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts", "brain.py"), "check", "--dump", dump, "--config", cfg, *more],
                           capture_output=True, text=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        return r.returncode, r.stdout

    def dump(self, **extra):
        d = tempfile.mkdtemp()
        write_dump(d, {"VH-1": {"state": "open", "release": "r-a", "minutes": 100, "time": "100m", "note": ""}}, {"r-a": {"name": "V2.8"}}, **extra)
        return d

    def test_a_clean_dump_with_every_collection_exits_zero_and_prints_the_table_and_lane_lines(self):
        d = self.dump(intake={}, threads=TH, links=full_links(), accuracy={"a": {"kind": "rollup", "lanes": 8, "priced": 1860, "elapsed": 280}})
        code, out = self.run_cmd(d, "--table")
        self.assertEqual(code, 0, out); self.assertIn("| V2.8 | 1 | 100 |", out); self.assertIn("LANE PACE V2.8", out)

    def test_a_document_only_release_is_forecast_as_build_with_no_store_upload_and_no_overhead_warning(self):
        d = tempfile.mkdtemp()
        write_dump(d, {"VH-1": {"state": "open", "release": "r-a", "minutes": 100, "time": "100m", "note": ""},
                       "VH-2": {"state": "open", "release": "r-d", "kind": "research", "minutes": 800, "time": "800m", "note": ""},
                       "VH-3": {"state": "open", "release": "r-d", "kind": "document", "minutes": 480, "time": "480m", "note": ""}},
                   {"r-a": {"name": "V2.8"}, "r-d": {"name": "V2.14"}})
        code, out = self.run_cmd(d, "--table")
        self.assertEqual(code, 0, out)
        self.assertIn("| V2.14 | 2 | 1280 | 7h02 build, no store upload |", out)   # 1280 x 0.33 = 422 minutes, no 375 of overhead
        self.assertIn("| V2.8 | 1 | 100 | 6h48 |", out)                            # a store release still pays it: 33 + 375
        self.assertNotIn("V2.14: release overhead", out)

    def test_a_planted_intake_and_thread_fault_each_fail_the_run(self):
        bad = {"aaaa1111bbbb2222cccc": {"status": "logged", "title": "x", "resolvedAt": "z", "outcome": "ok"}}
        code, out = self.run_cmd(self.dump(intake=bad)); self.assertEqual(code, 1, out); self.assertIn("logged with no ref", out)
        code, out = self.run_cmd(self.dump(threads=TH, links={})); self.assertEqual(code, 1, out); self.assertIn("Backlog does not feed", out)

    def test_the_state_block_is_written_from_a_fresh_read_and_never_from_a_stale_one(self):
        import time
        d = self.dump(); md = os.path.join(d, "B.md"); open(md, "w").write("# Backlog\n\nintro\n")
        code, out = self.run_cmd(d, "--state-block", md)
        self.assertEqual(code, 0, out); self.assertIn(BEGIN, open(md).read())
        old = time.time() - 3600
        os.utime(os.path.join(d, "items"), (old, old)); open(md, "w").write("# Backlog\n\nintro\n")
        code, out = self.run_cmd(d, "--state-block", md)
        self.assertEqual(code, 1, out); self.assertNotIn(BEGIN, open(md).read())


if __name__ == "__main__":
    unittest.main()
