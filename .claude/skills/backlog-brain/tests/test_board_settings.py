"""The board page's settings and the seed for a new board (VH-584).

Three layers. The pack's own rules (brain/board.py) run everywhere. The page's settings block is read out of
assets/board/board.html and run in node, so the page and the pack must agree on the defaults, on which documents are
valid, and on the guide's wording; that runs wherever node is, the mutation harness included. Three browser checks
render the page with assets/board/render_board.cjs: another project's settings reach every place they should, this
project's settings draw exactly what no settings draws, and a board built only from the seed takes the page's own writes
with a store that refuses an update to a missing document, as the platform does."""
import copy, json, os, re, shutil, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
from brain import board  # noqa: E402
from brain.guide import load_guide  # noqa: E402
from brain.model import ConfigError, load_config  # noqa: E402

PACK = os.path.join(HERE, "..")
PAGE = os.path.join(PACK, "assets", "board", "board.html")
RENDER = os.path.join(PACK, "assets", "board", "render_board.cjs")
BRAIN = os.path.join(PACK, "scripts", "brain.py")
EXAMPLE = os.path.join(PACK, "assets", "config.example.json")
PLAYWRIGHT = os.environ.get("PLAYWRIGHT_CORE") or os.path.abspath(os.path.join(HERE, "..", "..", "..", "..", "node_modules", "playwright-core"))
OTHER = {"schema": 1, "organisation": "Acme Ltd", "project": "Harbour Works", "refPrefix": "HW-", "budget": {"floorMin": 480, "capMin": 600},
         "overheadMin": 90, "store": None, "rounds": None, "horizon": 2, "sync": {"staleMin": 120, "refreshWaitMin": 10, "idleChecks": 5},
         "source": {"name": "the build log", "detail": "", "command": "", "onRelease": ""}}


def example():
    return json.load(open(EXAMPLE))


def page_block():
    src = open(PAGE, encoding="utf-8").read()
    m = re.search(r"/\*SETTINGS:BEGIN\*/(.*?)/\*SETTINGS:END\*/", src, re.S)
    return m.group(1) if m else None


def run_page(expr, **inputs):
    """Evaluates expr against the page's settings block in node, with inputs bound as constants, and returns its JSON value."""
    block = page_block()
    if block is None:
        raise AssertionError("the page has no settings block")
    head = "".join(f"const {k} = {json.dumps(v, ensure_ascii=False)};\n" for k, v in inputs.items())
    js = f"{block}\n{head}console.log(JSON.stringify({expr}));"
    r = subprocess.run(["node", "-e", js], capture_output=True, text=True)
    if r.returncode:
        raise AssertionError(r.stderr[-800:])
    return json.loads(r.stdout)


class Rules(unittest.TestCase):
    def test_the_example_record_gives_a_board_with_no_store_and_no_rule(self):
        s = board.settings_doc(load_config(example()))
        self.assertEqual((s["project"], s["refPrefix"], s["budget"], s["organisation"]), ("My Project", "PRJ-", {"floorMin": 720, "capMin": 840}, ""))
        self.assertIsNone(s["store"])
        self.assertIsNone(s["rounds"])
        self.assertEqual(s["source"], {"name": "delivery", "detail": "", "command": "", "onRelease": ""})

    def test_a_board_section_reaches_the_document(self):
        cfg = dict(example(), board={"organisation": "Acme Ltd", "store": {"name": "Play Store"}, "rounds": {"limit": 6, "label": "three-round rule"},
                                     "horizon": 2, "sync": {"stale_min": 120}, "source": {"name": "the build log", "on_release": "Tell the team."}})
        s = board.settings_doc(load_config(cfg))
        self.assertEqual((s["organisation"], s["store"], s["rounds"], s["horizon"]), ("Acme Ltd", {"name": "Play Store"}, {"limit": 6, "label": "three-round rule"}, 2))
        self.assertEqual(s["sync"], {"staleMin": 120, "refreshWaitMin": 15, "idleChecks": 3})
        self.assertEqual(s["source"], {"name": "the build log", "detail": "", "command": "", "onRelease": "Tell the team."})

    def test_a_bad_board_section_refuses_the_whole_record_and_lists_every_problem(self):
        bad = {"organisation": "two\nlines", "store": {"name": ""}, "rounds": {"limit": 0, "label": "x"}, "horizon": 13,
               "sync": {"stale_min": 0}, "source": {"name": ""}, "url": "https://example.com/board"}
        with self.assertRaises(ConfigError) as e:
            load_config(dict(example(), board=bad))
        text = " ".join(e.exception.problems)
        for where in ("board.organisation", "board.store.name", "board.rounds.limit", "board.horizon", "board.sync.stale_min", "board.source.name", "board.url"):
            self.assertIn(where, text)

    def test_the_page_limits_are_checked_where_the_board_is_built_and_nowhere_else(self):
        self.assertEqual(board.RESERVED_GATES, ("build", "upload"))
        def refused(change, words):
            cfg = example(); change(cfg)
            loaded = load_config(cfg)                               # the planner still takes it
            with self.assertRaises(ConfigError) as e:
                board.settings_doc(loaded)                          # the board does not
            self.assertIn(words, " ".join(e.exception.problems))
        refused(lambda c: c["gates"].append({"key": "build", "minutes": 5}), "gate key 'build' is reserved")
        refused(lambda c: c["gates"].append({"key": "upload", "minutes": 5}), "gate key 'upload' is reserved")
        refused(lambda c: c["gates"].append({"key": "a/b", "minutes": 5}), "cannot be a board document id")
        refused(lambda c: c["gates"].append({"key": "x", "minutes": 5, "lane": "side"}), "lane must be main or review")
        refused(lambda c: c["releases"].update(cap_min=840.5), "releases.cap_min must be whole minutes")
        refused(lambda c: c["releases"].update(cap_min=200000), "releases.cap_min must be whole minutes")
        refused(lambda c: c["releases"].update(cap_min=float("inf")), "releases.cap_min must be whole minutes")
        refused(lambda c: c["releases"].update(naming="R{major}.{minor}"), "releases.naming must be V{major}.{minor}")
        refused(lambda c: c["project"].update(name="x" * 81), "project.name, for the board page,")
        refused(lambda c: c["project"].update(ref_prefix="ABCDEFGHIJKL-"), "project.ref_prefix must be 1 to 11")

    def test_an_older_installers_record_still_plans_and_says_why_it_cannot_seed(self):
        cfg = example(); cfg["gates"] = [{"key": "tests", "minutes": 0, "triggers": ["src/*"]}, {"key": "build", "minutes": 0, "triggers": ["Dockerfile"]}]
        d = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, d, True)
        json.dump(cfg, open(os.path.join(d, "c.json"), "w")); json.dump([{"ref": "PRJ-1", "minutes": 30}], open(os.path.join(d, "i.json"), "w"))
        plan = subprocess.run([sys.executable, BRAIN, "plan", "--config", os.path.join(d, "c.json"), "--items", os.path.join(d, "i.json")], capture_output=True, text=True)
        self.assertEqual(plan.returncode, 0, plan.stdout + plan.stderr)
        seed = subprocess.run([sys.executable, BRAIN, "board", "seed", "--config", os.path.join(d, "c.json")], capture_output=True, text=True)
        self.assertEqual(seed.returncode, 2); self.assertIn("rename it 'container'", seed.stderr)

    def test_a_board_setting_the_pack_does_not_know_or_a_name_too_long_for_the_page_is_refused(self):
        with self.assertRaises(ConfigError) as e:
            load_config(dict(example(), board={"stor": {"name": "Play Store"}}))
        self.assertIn("board.stor is not a board setting", " ".join(e.exception.problems))
        with self.assertRaises(ConfigError):                        # 21 characters, 42 as the page counts them
            load_config(dict(example(), board={"store": {"name": "\U0001F6A2" * 21}}))
        load_config(dict(example(), board={"store": {"name": "\U0001F6A2" * 20}}))

    def test_the_words_for_hours(self):
        self.assertEqual([board.hours_text(m) for m in (720, 840, 810, 1409, 480)], ["12", "14", "13.5", "23.48", "8"])
        tail = " of fixed work for checks, packaging and upload"
        self.assertEqual([board.overhead_text(m) for m in (45, 60, 120, 375, 390, 90)],
                         [w + tail for w in ("about 45 minutes", "1 hour", "2 hours", "a little over 6 hours", "a little under 7 hours", "a little under 2 hours")])
        self.assertEqual(board.overhead_text(0), "fixed work for checks, packaging and upload, not yet measured")   # never "measured" when it is not
        self.assertEqual(board.overhead_text(375, store=False), "a little over 6 hours of fixed work for checks, packaging and release")

    def test_the_guide_fills_from_the_settings_and_drops_the_store_job_without_a_store(self):
        g = load_guide()["board"]
        today = board.fill_guide(g)
        self.assertIn("about 12 to 14 hours", today["intro"])
        self.assertIn("upload", [j["id"] for j in today["jobs"]])
        other = board.fill_guide(g, OTHER)
        self.assertIn("about 8 to 10 hours", other["intro"])
        self.assertNotIn("upload", [j["id"] for j in other["jobs"]])
        flat = json.dumps(other, ensure_ascii=False)
        self.assertIn("HW-318", flat); self.assertIn("Refresh from the build log", flat); self.assertNotIn("{", flat.replace('{"', "").replace("{}", ""))


class Seed(unittest.TestCase):
    def cfg(self, store=True):
        c = example()
        if store:
            c["board"] = {"store": {"name": "App Store"}}
        return load_config(c)

    def test_the_batch_creates_every_document_the_page_later_updates(self):
        b = board.seed(self.cfg(), "2026-10-07T11:00:00.000Z")
        self.assertEqual(b["action"], "batch")
        got = [(w["collection"], w["doc_id"]) for w in b["writes"]]
        self.assertEqual(got[:2], [("board", "settings"), ("board", "meta")])
        self.assertEqual([d for c, d in got if c == "plan"], ["r-v1-0", "r-v1-1", "r-v1-2", "r-v1-3", "r-v1-4"])   # current and the horizon
        self.assertIn(("releases", "1-0-0"), got)
        self.assertEqual([d for c, d in got if c == "gates"], ["review", "upload"])                                # the store's upload last
        self.assertTrue(all(w["op"] == "set" and "if_version" not in w for w in b["writes"]))                      # every write creates
        meta = b["writes"][1]["data"]
        self.assertEqual((meta["currentRelease"], meta["nextRelease"], meta["buildRate"], meta["releaseStepsMin"]), ("V1.0", "V1.1", 1.0, 0))
        plan = {w["doc_id"]: w["data"] for w in b["writes"] if w["collection"] == "plan"}
        self.assertEqual([p["status"] for p in plan.values()], ["current"] + ["planned"] * 4)

    def test_no_store_means_no_upload_gate(self):
        got = [w["doc_id"] for w in board.seed(self.cfg(store=False), "2026-10-07T11:00:00.000Z")["writes"] if w["collection"] == "gates"]
        self.assertEqual(got, ["review"])

    def test_a_batch_over_fifty_writes_is_refused(self):
        c = example(); c["gates"] = [{"key": f"g{i}", "minutes": 1} for i in range(45)]
        with self.assertRaises(ValueError):
            board.seed(load_config(c), "2026-10-07T11:00:00.000Z")

    def test_the_command_prints_the_batch_and_refuses_a_bad_record(self):
        ok = subprocess.run([sys.executable, BRAIN, "board", "seed", "--config", EXAMPLE, "--now", "2026-10-07T11:00:00.000Z"], capture_output=True, text=True)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertEqual(json.loads(ok.stdout)["writes"][0]["doc_id"], "settings")
        d = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, d, True)
        bad = example(); bad["gates"].append({"key": "upload", "minutes": 1}); json.dump(bad, open(os.path.join(d, "c.json"), "w"))
        no = subprocess.run([sys.executable, BRAIN, "board", "seed", "--config", os.path.join(d, "c.json")], capture_output=True, text=True)
        self.assertEqual(no.returncode, 2)
        self.assertIn("reserved", no.stderr)
        gone = subprocess.run([sys.executable, BRAIN, "guide", "--for", "board", "--config", os.path.join(d, "missing.json")], capture_output=True, text=True)
        self.assertEqual(gone.returncode, 2); self.assertIn("cannot read the settings record", gone.stderr)


@unittest.skipUnless(os.path.exists(PAGE), "the board page is not in this copy of the pack")
class PageWiring(unittest.TestCase):
    """The browser checks are left out of selfcheck, so the wiring they would catch is also pinned here, in the source."""
    def test_the_page_reads_its_settings_document_and_applies_it(self):
        src = open(PAGE, encoding="utf-8").read()
        self.assertEqual(src.count('db.doc("board/settings").onSnapshot(s => { S = boardSettings(s.exists ? s.data() : null); applySettings(); render(); }'), 1)
        self.assertEqual(src.count("  applySettings();\n  render();\n"), 1)          # the defaults are applied before the first draw
        self.assertEqual(src.count("let S = boardSettings(null);"), 1)


@unittest.skipUnless(shutil.which("node") and os.path.exists(PAGE), "node and the board page are needed")
class PageAgreesWithThePack(unittest.TestCase):
    def test_the_page_and_the_pack_hold_the_same_defaults(self):
        self.assertEqual(run_page("BOARD_DEFAULTS"), board.PAGE_DEFAULTS)
        self.assertEqual(run_page("boardSettings(null)"), board.PAGE_DEFAULTS)

    def test_the_page_takes_every_document_the_pack_writes_unchanged(self):
        docs = [board.PAGE_DEFAULTS, OTHER, board.settings_doc(load_config(example())),
                board.settings_doc(load_config(dict(example(), board={"store": {"name": "Play Store"}, "rounds": {"limit": 6, "label": "three-round rule"}})))]
        self.assertEqual(run_page("docs.map(boardSettings)", docs=docs), docs)

    def test_a_bad_field_falls_back_alone_and_null_switches_a_feature_off(self):
        bad = dict(OTHER, project="", refPrefix="H W", budget={"floorMin": 700, "capMin": 600}, horizon=99, organisation="a\u0007b",
                   source={"name": "x" * 41, "detail": 3, "command": "", "onRelease": ""}, sync={"staleMin": 0, "refreshWaitMin": 10, "idleChecks": 5})
        got = run_page("boardSettings(bad)", bad=bad)
        d = board.PAGE_DEFAULTS
        self.assertEqual((got["project"], got["refPrefix"], got["budget"], got["horizon"], got["organisation"]),
                         (d["project"], d["refPrefix"], d["budget"], d["horizon"], d["organisation"]))
        self.assertEqual(got["source"], {"name": "delivery", "detail": d["source"]["detail"], "command": "", "onRelease": ""})
        self.assertEqual(got["sync"], {"staleMin": 90, "refreshWaitMin": 10, "idleChecks": 5})
        self.assertIsNone(got["store"]); self.assertIsNone(got["rounds"])
        missing = run_page("boardSettings({store: {name: ''}, rounds: {limit: 4}})")
        self.assertEqual((missing["store"], missing["rounds"]), (d["store"], d["rounds"]))   # a broken object is not a switch-off

    def test_the_words_agree(self):
        mins = [0, 45, 60, 90, 120, 375, 390, 480, 600, 720, 810, 840, 1409]
        self.assertEqual(run_page("mins.map(hoursText)", mins=mins), [board.hours_text(m) for m in mins])
        for store in (True, False):
            self.assertEqual(run_page("mins.map(m => overheadText(m, store))", mins=mins, store=store), [board.overhead_text(m, store) for m in mins])

    def test_the_guide_reads_the_same_on_the_page_and_in_the_pack(self):
        g = load_guide()["board"]
        for s in (board.PAGE_DEFAULTS, OTHER):
            want = board.fill_guide(g, s)
            want = {"title": want["title"], "intro": want["intro"], "who": want.get("who", []),
                    "jobs": [{"id": j["id"], "title": j["title"], "steps": j["steps"]} for j in want["jobs"]]}
            self.assertEqual(run_page("fillGuide(g, s)", g=g, s=s), want)


def why_not():
    if os.environ.get("BRAIN_SKIP_BROWSER") or os.environ.get("BRAIN_SELFCHECK_RUNNING"):
        return "browser checks are left to a direct selftest"
    if not os.path.exists(PAGE) or not os.path.exists(RENDER):
        return "the board page is not in this copy of the pack"
    if not shutil.which("node") or not os.path.isdir(PLAYWRIGHT):
        return "node or playwright-core is not installed"
    return None


def fixture(settings=None, store_gate=False, main_gate=True, refresh=True):
    """A small board in another project's shape: two releases, three items, two gates and a past release over four rounds. Its
    pipeline was read 20 minutes before the render's clock and a refresh was asked 12 minutes before it, so the stale and the
    refresh-wait settings each fall on one side or the other of today's 90 and 15."""
    s = {"plan": {"r-cur": {"key": "r-cur", "name": "V3.1", "status": "current", "order": 1, "focus": "Harbour lights"},
                  "r-nxt": {"key": "r-nxt", "name": "V3.2", "status": "planned", "order": 2, "focus": "Not yet planned"}},
         "items": {"HW-1": {"ref": "HW-1", "state": "open", "release": "r-cur", "minutes": 120, "priority": "high", "task": "Light the quay"},
                   "HW-2": {"ref": "HW-2", "state": "built", "release": "r-cur", "minutes": 60, "priority": "med", "task": "Paint the bollards"},
                   "HW-3": {"ref": "HW-3", "state": "open", "release": "r-nxt", "minutes": 90, "priority": "low", "task": "Survey the slipway"}},
         "gates": {"review": {"key": "review", "label": "code review", "short": "Review", "lane": "review", "status": "pending", "rounds": [], "order": 1},
                   "tests": {"key": "tests", "label": "test suite", "short": "Tests", "lane": "main", "status": "pending", "rounds": [], "order": 2}},
         "releases": {"3-0-0": {"version": "3.0.0", "status": "past", "order": 0, "rounds": [{"verdict": v} for v in ("PASS", "FAIL", "FAIL", "PASS", "FAIL", "PASS")]},
                      "3-1-0": {"version": "3.1.0", "status": "current", "order": 1, "rounds": []}},
         "accuracy": {"a": {"ref": "HW-0", "est": 60, "actual": 30}},
         "board": {"meta": {"currentRelease": "V3.1", "nextRelease": "V3.2", "updatedAt": "2026-10-07T09:58:00.000Z",
                            "pipelineSyncedAt": "2026-10-07T09:40:00.000Z", "pipelineSyncedFrom": "abc1234", "releaseStepsMin": 90,
                            "refreshRequestedAt": "2026-10-07T09:48:00.000Z"}}}
    if not main_gate:
        del s["gates"]["tests"]
    if not refresh:
        del s["board"]["meta"]["refreshRequestedAt"]
    if store_gate:
        s["gates"]["upload"] = {"key": "upload", "label": "Store upload", "short": "Upload", "lane": "main", "status": "pending", "rounds": [], "order": 3}
    if settings is not None:
        s["board"]["settings"] = settings
    return s


@unittest.skipIf(why_not(), why_not())
class InABrowser(unittest.TestCase):
    def render(self, store, mode, folds=""):
        d = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, d, True)
        json.dump(store, open(os.path.join(d, "store.json"), "w"), ensure_ascii=False)
        r = subprocess.run(["node", RENDER, PAGE, os.path.join(d, "store.json"), os.path.join(d, "out"), mode], capture_output=True, text=True,
                           timeout=300, env=dict(os.environ, PLAYWRIGHT_CORE=PLAYWRIGHT, BOARD_OPEN_FOLDS=folds))
        if r.returncode == 2 and "No Chromium found" in r.stderr:
            self.skipTest("no Chromium found")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return (json.loads(r.stdout.strip().splitlines()[-1]) if mode != "shot" else r.stdout), os.path.join(d, "out")

    def test_another_projects_settings_reach_every_place_they_should(self):
        f, _ = self.render(fixture(OTHER, store_gate=True), "probe")          # an upload gate left on a board with no store
        self.assertEqual(f["errors"], [])
        self.assertEqual(f["brand"], "Acme Ltd · Harbour Works")
        self.assertEqual(f["uploadLabel"], "Time to release"); self.assertNotIn("store refusals", f["uploadSub"])
        self.assertFalse(f["uploadNode"]); self.assertFalse(any("Upload" in n for n in f["nodes"]), f["nodes"])
        self.assertEqual(f["refresh"], "Ask again")                         # asked 12 minutes ago, past this board's 10
        self.assertIn("the build log's own record at", f["pipeSrc"]); self.assertNotIn("gate table", f["pipeSrc"])
        self.assertFalse(f["pipeStale"])                                    # read 20 minutes ago, inside this board's 120
        self.assertFalse(f["roundLine"]); self.assertNotIn("over the rule", f["histSub"])
        self.assertFalse(any("· upload" in t for t in f["tabs"]), f["tabs"])
        self.assertIn("against an 8 to 10h budget", f["heading"]); self.assertIn("release", f["heading"])
        self.assertFalse(any("Store refusals" in t for t in f["foot"]), f["foot"]); self.assertTrue(any("Forecast to release" in t for t in f["foot"]), f["foot"])
        self.assertNotIn("upload", f["guideJobs"]); self.assertIn("about 8 to 10 hours", f["guideIntro"])
        self.assertIn("HW-318", f["guideText"]); self.assertIn("a little under 2 hours of fixed work for checks, packaging and release", f["guideText"])
        self.assertEqual(f["mergeHint"], "Type a ref, such as HW-123, or pick from the list")
        self.assertIn("Paste logs or code", f["detailLabel"])
        custom = dict(OTHER, store={"name": "Play Store"}, rounds={"limit": 6, "label": "three-round rule"}, sync={"staleMin": 5, "refreshWaitMin": 30, "idleChecks": 3})
        st, _ = self.render(fixture(custom, store_gate=True), "probe")
        self.assertEqual(st["errors"], [])
        self.assertTrue(st["uploadNode"]); self.assertEqual(st["popTitle"], "Play Store upload"); self.assertEqual(st["uploadLabel"], "Time to upload")
        self.assertIn("upload", st["guideJobs"]); self.assertTrue(st["roundLine"])
        self.assertEqual(st["roundLabel"], "Dashed line: the three-round rule"); self.assertIn("0 over the rule", st["histSub"])   # 6 rounds is not over 6
        self.assertTrue(st["pipeStale"]); self.assertIn("Over 20m old", st["pipeSrc"])                                           # past 5, and under an hour
        self.assertEqual(st["refresh"], "Refreshing")                                                                           # 12 minutes, inside 30
        lone, _ = self.render(fixture(OTHER, main_gate=False, refresh=False), "probe")     # review gates and nothing after them
        self.assertEqual(lone["errors"], []); self.assertTrue(any(n.startswith("code review") for n in lone["nodes"]), lone["nodes"])
        self.assertEqual(lone["refresh"], "Refresh from the build log")                     # no refresh waiting: the button names the source

    def test_this_projects_settings_draw_exactly_what_no_settings_draws_and_what_it_drew_before(self):
        none, a = self.render(fixture(None, store_gate=True), "probe")
        vf, b = self.render(fixture(board.PAGE_DEFAULTS, store_gate=True), "probe")
        self.assertEqual(none, vf)
        # Pinned from the page as it was before settings existed (d4db0ac4), measured on this fixture on 2026-10-07: a change to
        # what this board draws with no settings fails here, whatever font the machine has.
        self.assertEqual(none["brand"], "Bluestaq Limited · Vendor Fishing")
        self.assertEqual((none["uploadLabel"], none["popTitle"], none["refresh"]), ("Time to upload", "App Store upload", "Refreshing"))
        self.assertTrue(none["uploadNode"]); self.assertFalse(none["pipeStale"])
        self.assertIn("Read from delivery's own record (gate table, eval record and commits) at abc1234", none["pipeSrc"])
        self.assertIn(": Claude is reading delivery's record", none["pipeSrc"])
        self.assertEqual(none["roundLabel"], "Dashed line: the two-round rule, 2 gates × 2 rounds"); self.assertIn("1 over the rule", none["histSub"])
        self.assertIn("against a 12 to 14h budget", none["heading"]); self.assertIn(", upload ", none["heading"])
        self.assertTrue(any("Store refusals:" in t for t in none["foot"])); self.assertTrue(any("Forecast to upload, range" in t for t in none["foot"]))
        self.assertTrue(any(" · upload " in t for t in none["tabs"]), none["tabs"])
        self.assertIn("store refusals", none["uploadSub"])
        self.assertEqual(none["mergeHint"], "Type a ref, such as VH-123, or pick from the list")
        self.assertEqual(none["detailLabel"], "Detail, evidence or where you saw it (optional). Paste store feedback, logs or code in full: line breaks and layout are kept")
        self.assertEqual(none["guideIntro"], "I keep one list of everything to build and split it into releases. Each release is sized to take about 12 to 14 hours to build and ship. Find the job you came to do below and follow the steps.")
        self.assertIn("A release forecast is the build time plus a little over 6 hours of fixed work for checks, packaging and upload.", none["guideText"])
        self.assertIn("like VH-318", none["guideText"]); self.assertIn("press Refresh from delivery.", none["guideText"])
        self.assertEqual(none["guideJobs"][-2:], ["upload", "wrong"])
        for folds in ("", "1"):
            _, sa = self.render(fixture(None, store_gate=True), "shot", folds)
            _, sb = self.render(fixture(board.PAGE_DEFAULTS, store_gate=True), "shot", folds)
            for name in ("desktop.png", "phone.png", "guide.png"):
                with open(os.path.join(sa, name), "rb") as x, open(os.path.join(sb, name), "rb") as y:
                    self.assertEqual(x.read(), y.read(), f"{name} differs (charts {'open' if folds else 'shut'})")

    def test_a_board_built_only_from_the_seed_takes_the_pages_own_writes(self):
        cfg = load_config(dict(example(), board={"store": {"name": "App Store"}, "horizon": 2, "source": {"command": "make sync"}}))
        store = {}
        for w in board.seed(cfg, "2026-10-07T09:58:00.000Z")["writes"]:
            store.setdefault(w["collection"], {})[w["doc_id"]] = w["data"]
        out, _ = self.render(copy.deepcopy(store), "writes")
        self.assertEqual(out["errors"], [])
        self.assertEqual(out["refreshed"], "Refresh asked, Claude told")
        self.assertEqual(out["marked"], "Upload marked passed, Claude told")
        self.assertLessEqual(set(out["rejected"]), {"releases/1-1-0"}, out["rejected"])    # the page catches that one and creates it
        s = out["store"]
        self.assertEqual((s["plan"]["r-v1-0"]["status"], s["plan"]["r-v1-1"]["status"], s["board"]["meta"]["currentRelease"]), ("released", "current", "V1.1"))
        self.assertIn("r-v1-3", s["plan"]); self.assertNotIn("r-v1-4", s["plan"])            # the horizon of 2 holds after the roll, not today's 4
        self.assertTrue(all(g["status"] == "pending" for g in s["gates"].values()))
        self.assertTrue(out["told"] and out["told"][-1].startswith("UPLOAD PASSED") and "liaison" not in out["told"][-1], out["told"])
        self.assertIn("Re-read delivery's record now (make sync) and update", out["told"][0])   # this project's command, not sync_pipeline.py
        del store["board"]["meta"]
        bare, _ = self.render(store, "writes")
        self.assertIn("board/meta", bare["rejected"])                                       # the stub can say no, so the yes above means something
        # The platform refuses it with invalid_argument, which the page reads as no permission: misleading for a missing
        # document, and on-screen wording, so it waits for the owner (recorded in docs/DEV3-STATUS.md, VH-584).
        self.assertEqual(bare["refreshed"], "You do not have permission to change this board.")


if __name__ == "__main__":
    unittest.main()
