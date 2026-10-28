import copy, json, os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from brain.model import load_config, ConfigError, item_gates, normalise_item
from brain.optimiser import plan, forecast_min
from brain.resources import pace_table, pick_pace, forecast
from brain.api import run
from brain.threads import brief, session_request, branch_for, lanes_disjoint, session_id_of, thread_link, backlog_session

CFG = {"schema": 1, "project": {"name": "T", "ref_prefix": "T-"},
       "releases": {"start": "V1.0", "floor_min": 300, "cap_min": 600, "overhead_min": 200, "pace": 1.0, "target_min": 600},
       "gates": [{"key": "eng", "minutes": 40, "triggers": ["src/*"]}, {"key": "design", "minutes": 30, "triggers": ["public/*"]}],
       "people": [{"id": "ann", "hours_per_week": 20}], "agents": {"max_concurrent": 2}}


def item(ref, minutes, **kw):
    d = {"ref": ref, "minutes": minutes, "priority": "high", "files": ["src/a.js"]}
    d.update(kw)
    return d


def where(res, ref):
    for r in res["releases"]:
        if any(i["ref"] == ref for i in r["items"]):
            return r["name"]
    return None


def cfg(**rel):
    c = copy.deepcopy(CFG)
    c["releases"].update(rel)
    return load_config(c)


class Settings(unittest.TestCase):
    def test_every_problem_is_reported_together_and_nothing_is_half_applied(self):
        bad = {"schema": 9, "project": {}, "releases": {"floor_min": 900, "cap_min": 600}}
        with self.assertRaises(ConfigError) as cm:
            load_config(bad)
        self.assertGreaterEqual(len(cm.exception.problems), 4)

    def test_an_item_with_no_files_or_gates_triggers_every_gate(self):
        c = cfg()
        self.assertEqual(item_gates({"ref": "x"}, c), {"eng", "design"})
        self.assertEqual(item_gates({"ref": "x", "files": ["src/a.js"]}, c), {"eng"})
        self.assertEqual(item_gates({"ref": "x", "gates": ["design"]}, c), {"design"})


class Optimiser(unittest.TestCase):
    def test_the_same_inputs_give_the_same_plan(self):
        items = [item(f"T-{n}", 40 + n) for n in range(12)]
        a, b = plan(items, cfg()), plan(list(reversed(items)), cfg())
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))

    def test_no_release_exceeds_the_cap(self):
        res = plan([item(f"T-{n}", 60) for n in range(30)], cfg())
        for r in res["releases"]:
            self.assertLessEqual(r["forecast_min"], 600)
        self.assertEqual(sum(len(r["items"]) for r in res["releases"]), 30)

    def test_a_dependency_is_never_placed_before_what_it_needs(self):
        items = [item("T-1", 100, deps=["T-2"]), item("T-2", 100, deps=["T-3"]), item("T-3", 100)]
        res = plan(items, cfg(cap_min=420, target_min=420))
        names = [where(res, f"T-{n}") for n in (3, 2, 1)]
        self.assertEqual(names, sorted(names))
        order = [i["ref"] for r in res["releases"] for i in r["items"]]
        self.assertLess(order.index("T-3"), order.index("T-2"))
        self.assertLess(order.index("T-2"), order.index("T-1"))

    def test_a_locked_item_stays_in_its_release(self):
        items = [item("T-1", 50, lock="V1.2", priority="low")] + [item(f"T-{n}", 100) for n in range(2, 12)]
        self.assertEqual(where(plan(items, cfg()), "T-1"), "V1.2")

    def test_waiting_and_research_items_take_no_release_capacity(self):
        res = plan([item("T-1", 100), item("T-2", 900, needs_owner=True), item("T-3", 900, kind="research")], cfg())
        self.assertEqual(res["releases"][0]["priced"], 100)
        self.assertEqual([w["ref"] for w in res["waiting"]], ["T-2"])
        self.assertEqual([w["ref"] for w in res["off_path"]], ["T-3"])

    def test_tooling_work_is_planned_apart_and_carries_no_overhead(self):
        res = plan([item("T-1", 100), item("T-2", 200, track="tooling")], cfg())
        self.assertEqual(res["tooling"]["priced"], 200)
        self.assertEqual(res["releases"][0]["priced"], 100)

    def test_a_low_priority_item_rides_a_release_that_already_pays_for_its_gate(self):
        c = cfg(cap_min=520, target_min=520, floor_min=100)
        items = [item("S-1", 120, files=["src/a.js"]), item("S-2", 120, files=["src/b.js"]),
                 item("C-1", 120, files=["public/a.js"]), item("C-2", 120, files=["public/b.js"]),
                 item("RIDER", 40, priority="low", files=["src/c.js"])]
        res = plan(items, c)
        self.assertEqual(where(res, "RIDER"), where(res, "S-1"))
        reason = [i["reason"] for r in res["releases"] for i in r["items"] if i["ref"] == "RIDER"][0]
        self.assertIn("rider", reason)

    def test_a_release_with_fewer_gates_forecasts_lower(self):
        c = cfg()
        self.assertLess(forecast_min(c, 100, {"eng"}), forecast_min(c, 100, {"eng", "design"}))

    def test_items_that_share_a_file_share_a_lane_and_lanes_respect_the_agent_limit(self):
        items = [item("T-1", 50, files=["src/x.js"]), item("T-2", 60, files=["src/x.js"]),
                 item("T-3", 70, files=["src/y.js"]), item("T-4", 80, files=["src/z.js"])]
        rel = plan(items, cfg())["releases"][0]
        self.assertLessEqual(len(rel["lanes"]), 2)
        lane_of = {r: n for n, l in enumerate(rel["lanes"]) for r in l["refs"]}
        self.assertEqual(lane_of["T-1"], lane_of["T-2"])

    def test_a_dependency_cycle_is_reported_and_does_not_hang(self):
        res = plan([item("T-1", 10, deps=["T-2"]), item("T-2", 10, deps=["T-1"])], cfg())
        self.assertTrue(any("cycle" in w for w in res["warnings"]))

    def test_an_item_too_big_for_any_release_is_placed_alone_and_reported(self):
        res = plan([item("T-1", 2000)], cfg())
        self.assertEqual(where(res, "T-1"), "V1.0")
        self.assertTrue(any(w.startswith("T-1: needs") and "cap on its own" in w for w in res["warnings"]))

    def test_a_release_under_its_floor_is_filled_from_what_is_waiting(self):
        c = cfg(floor_min=450, cap_min=600, target_min=300)   # the main pass stops at 300, below the floor
        res = plan([item("T-1", 100, priority="high"), item("T-2", 100, priority="low", files=["public/a.js"])], c)
        self.assertEqual(where(res, "T-2"), "V1.0")
        self.assertIn("floor", [i["reason"] for i in res["releases"][0]["items"] if i["ref"] == "T-2"][0])


class Resources(unittest.TestCase):
    ROWS = [{"est": 100, "actual": a, "who": "ann", "kind": "build"} for a in (30, 35, 40, 50)] \
        + [{"est": 100, "actual": a, "who": "bob", "kind": "build"} for a in (80, 90)]

    def test_pace_falls_back_and_says_which_evidence_it_used(self):
        t, c = pace_table(self.ROWS), cfg()
        self.assertIn("person and kind", pick_pace(t, "ann", "build", c)[3])
        self.assertTrue(pick_pace(t, "bob", "build", c)[3].startswith("kind ("))   # only 2 rows for bob, so it falls back
        self.assertIn("settings", pick_pace(pace_table([]), "ann", "build", c)[3])

    def test_the_forecast_is_a_range_with_low_at_most_mid_at_most_high(self):
        res = run(CFG, [item("T-1", 100), item("T-2", 100, files=["src/q.js"])], self.ROWS)
        f = res["forecasts"][0]
        self.assertLessEqual(f["low_min"], f["mid_min"])
        self.assertLessEqual(f["mid_min"], f["high_min"])
        self.assertLessEqual(f["parallel_mid_min"], f["mid_min"])        # lanes at once can only be faster

    def test_a_release_that_asks_for_more_of_people_than_exists_is_warned(self):
        res = run(CFG, [item("T-1", 100, human_minutes=3000)], [])
        self.assertTrue(any("people" in w for w in res["warnings"]))

    def test_human_time_with_nobody_configured_is_reported(self):
        c = copy.deepcopy(CFG); c["people"] = []
        res = run(c, [item("T-1", 100, human_minutes=60)], [])
        self.assertTrue(any("no people are configured" in w for w in res["warnings"]))


class Threads(unittest.TestCase):
    T = [{"id": "t-b", "name": "Backlog", "role": "backlog", "url": "https://claude.ai/code/session_017hDQ4U"},
         {"id": "t-1", "name": "Development 1", "role": "development", "url": "https://claude.ai/code/session_01N3mtxg"},
         {"id": "n42", "name": "Development 2", "role": "development", "url": ""}]
    L = [{"from": "t-b", "to": "n42", "kind": "feeds work to"}, {"from": "n42", "to": "t-1", "kind": "hands branches to"}]
    LANE = [{"ref": "T-9", "minutes": 60, "task": "Do the nine thing"}]

    def req(self, **kw):
        return session_request(self.T[2], self.T, self.L, kw.get("lane", self.LANE), "Proj", "https://claude.ai/artifact/x", "https://github.com/o/r")

    def test_the_brief_carries_role_relationships_board_repository_and_lane(self):
        p = self.req()["prompt"]
        for needle in ("Development 2", "Development thread", "Backlog (session_017hDQ4U) feeds work to Development 2", "Development 2 hands branches to Development 1",
                       "session_01N3mtxg", "https://claude.ai/artifact/x", "https://github.com/o/r", "T-9", "CLAUDE.md"):
            self.assertIn(needle, p)

    def test_a_development_thread_gets_one_branch_and_other_roles_get_none(self):
        r = self.req()
        self.assertEqual(r["outcome_branch"], branch_for(self.T[2]))
        self.assertRegex(r["outcome_branch"], r"^claude/[a-z0-9-]+$")
        self.assertIn("Never push to another branch", r["prompt"])
        doc = dict(self.T[2], role="documentation")
        self.assertNotIn("outcome_branch", session_request(doc, self.T, self.L, [], "Proj", "b", "r"))

    def test_a_branch_is_built_from_the_name_never_from_free_text(self):
        t = {"id": "a/b;rm -rf", "name": "Dev ../../x $(id)", "role": "development"}
        self.assertRegex(branch_for(t), r"^claude/[a-z0-9-]+$")

    def test_a_thread_with_no_lane_is_told_to_start_nothing(self):
        self.assertIn("Do not start any work", self.req(lane=[])["prompt"])

    def test_a_nameless_thread_is_refused(self):
        with self.assertRaises(ValueError):
            brief({"id": "x", "name": "", "role": "development"}, self.T, self.L, [], "P", "b", "r")

    def test_two_threads_that_would_write_the_same_file_are_reported(self):
        self.assertEqual(lanes_disjoint({"A": ["src/x.js", "src/y.js"], "B": ["src/y.js"]}), [("src/y.js", "A", "B")])
        self.assertEqual(lanes_disjoint({"A": ["a"], "B": ["b"]}), [])

    def test_the_brief_says_how_to_make_the_branch_and_what_from(self):
        with_base = session_request(self.T[2], self.T, self.L, self.LANE, "P", "b", "r", base="claude/resume")["prompt"]
        self.assertIn("git checkout -b claude/development-2-n42 origin/claude/resume", with_base)
        self.assertIn("ask the Backlog thread which base branch", self.req()["prompt"])

    def test_the_link_is_read_from_the_session_tools_result_and_nothing_else_is_trusted(self):
        self.assertEqual(thread_link({"ccr": {"id": "session_01WFG9v7"}}), "https://claude.ai/code/session_01WFG9v7")
        for bad in ({}, {"ccr": {}}, {"ccr": {"id": "x; rm"}}, None):
            with self.assertRaises(ValueError):
                thread_link(bad)

    def test_other_threads_are_told_to_wake_backlog_and_why(self):
        p = self.req()["prompt"]
        self.assertIn("WAKE Backlog (session_017hDQ4U)", p)
        self.assertIn("this is what restarts it", p)
        doc = session_request(dict(self.T[2], role="documentation"), self.T, self.L, [], "P", "b", "r")["prompt"]
        self.assertIn("WAKE Backlog (session_017hDQ4U)", doc)
        bl = brief(self.T[0], self.T, self.L, [], "P", "b", "r")
        self.assertNotIn("WAKE", bl)                                   # Backlog does not wake itself
        nob = [t for t in self.T if t["role"] != "backlog"]
        self.assertIn("ask the owner for its session id", brief(self.T[2], nob, [], [], "P", "b", "r"))
        self.assertIsNone(backlog_session(nob))

    def test_every_thread_is_briefed_with_the_owners_ethos(self):
        # Owner, 2026-10-07: speed and efficiency balanced with quality and release standards, zero waste, zero duplication.
        for t in self.T:
            p = brief(t, self.T, self.L, [], "P", "b", "r")
            self.assertIn("HOW YOU WORK", p)
            self.assertIn("zero waste, zero duplication", p)
            self.assertIn("Never run a check twice on the same tree", p)

    def test_the_session_id_is_read_from_the_link(self):
        self.assertEqual(session_id_of("https://claude.ai/code/session_01N3mtxg"), "session_01N3mtxg")
        self.assertIsNone(session_id_of("https://example.com/x"))


class WorkedExample(unittest.TestCase):
    """The plan built by hand on 2026-10-01 for Vendor Fishing, re-derived from the same inputs."""
    def setUp(self):
        base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "example")
        self.cfg, self.items = json.load(open(os.path.join(base, "config.json"))), json.load(open(os.path.join(base, "items.json")))
        self.res = run(self.cfg, self.items, [])

    def test_every_open_store_item_is_placed_exactly_once_and_none_exceeds_the_cap(self):
        placed = [i["ref"] for r in self.res["releases"] for i in r["items"]]
        self.assertEqual(len(placed), len(set(placed)))
        expected = {i["ref"] for i in self.items if not i.get("needs_owner") and i.get("kind") != "research" and not i["ref"].startswith("VH-366")}
        self.assertEqual(set(placed), expected)
        for r in self.res["releases"]:
            self.assertLessEqual(r["forecast_min"], self.cfg["releases"]["cap_min"])

    def test_dependencies_and_locks_hold_in_the_worked_plan(self):
        pos = {i["ref"]: (n, k) for n, r in enumerate(self.res["releases"]) for k, i in enumerate(r["items"])}
        for it in self.items:
            for d in it.get("deps", []):
                if it["ref"] in pos and d in pos:
                    self.assertLessEqual(pos[d][0], pos[it["ref"]][0], f"{it['ref']} before {d}")
        for it in self.items:
            if it.get("lock") and it["ref"] in pos:
                self.assertEqual(self.res["releases"][pos[it["ref"]][0]]["name"], it["lock"])

    def test_the_storage_theme_lands_first_and_the_worked_plan_needs_no_more_releases_than_the_hand_plan(self):
        first = {i["ref"] for i in self.res["releases"][0]["items"]}
        self.assertTrue({"VH-363", "VH-364", "VH-344"} <= first)
        self.assertLessEqual(len(self.res["releases"]), 4)


if __name__ == "__main__":
    unittest.main()


class Stranded(unittest.TestCase):
    def test_an_item_locked_to_a_release_the_plan_never_reaches_is_reported_not_dropped(self):
        res = plan([item("A", 60), item("B", 60, lock="Safety")], cfg())
        self.assertIsNone(where(res, "B"))
        self.assertTrue(any(w.startswith("B: locked to Safety") for w in res["warnings"]), res["warnings"])
        self.assertIn("B", [w["ref"] for w in res["waiting"]])

    def test_a_clean_plan_has_no_stranded_item(self):
        res = plan([item("A", 60), item("B", 60)], cfg())
        self.assertFalse([w for w in res["warnings"] if "never reaches" in w])
        self.assertEqual(res["waiting"], [])
