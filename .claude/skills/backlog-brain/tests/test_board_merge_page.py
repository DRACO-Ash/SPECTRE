"""The board page's Merge into control (VH-377 B) in a real browser: assets/board/render_merge.cjs in test mode, against a small
board built here, must report every check holding and no page error. It runs wherever the page, node, playwright-core and a Chromium
are present, and is skipped otherwise, inside a self-check that is already running, and in the mutation harness (BRAIN_SKIP_BROWSER),
which measures the pack's own rules and would otherwise pay a browser start for every mutation."""
import json, os, shutil, subprocess, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE_DIR = os.path.abspath(os.path.join(HERE, "..", "assets", "board"))
PLAYWRIGHT = os.environ.get("PLAYWRIGHT_CORE") or os.path.abspath(os.path.join(HERE, "..", "..", "..", "..", "node_modules", "playwright-core"))
META = {"stages": ["Build", "Reviews", "Final check", "Package", "Upload"], "stageIndex": 0, "buildRate": 0.3, "releaseStepsMin": 154,
        "reviewFixesMin": 120, "currentRelease": "V9.1", "nextRelease": "V9.2", "updatedAt": "2026-10-07T04:00:00.000Z", "basis": "a test board"}
PLAN = {"r-cur": {"key": "r-cur", "name": "V9.1", "status": "current", "order": 1, "focus": "Test release"},
        "r-old": {"key": "r-old", "name": "V9.0", "status": "released", "order": 0, "focus": "Shipped"},
        "r-brain": {"key": "r-brain", "name": "Backlog Brain", "status": "planned", "order": 2, "focus": "Portable pack"}}
# Rows as wide as the live board's: the longest status label is what pushed the release table past its panel at 800 pixels
# (measured 2026-10-07: 133 pixels over with the old no-wrap breakpoint, 0 with the new), so the width check here can fail.
ITEMS = {r: {"ref": r, "state": st, "release": "r-cur", "minutes": m, "priority": "high", "task": "Task " + r, "note": ""}
         for r, st, m in (("VH-318-A", "answered", 130), ("VH-318-I", "needscheck", 75), ("VH-1", "open", 30))}


def why_not():
    if os.environ.get("BRAIN_SKIP_BROWSER") or os.environ.get("BRAIN_SELFCHECK_RUNNING"):
        return "browser checks are left to a direct selftest"
    if not os.path.exists(os.path.join(PAGE_DIR, "board.html")) or not os.path.exists(os.path.join(PAGE_DIR, "render_merge.cjs")):
        return "the board page is not in this copy of the pack"
    if not shutil.which("node") or not os.path.isdir(PLAYWRIGHT):
        return "node or playwright-core is not installed"
    return None


@unittest.skipIf(why_not(), why_not())
class MergeIntoInABrowser(unittest.TestCase):
    def test_every_merge_into_check_holds_on_the_page(self):
        d = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, d, True)
        for name, docs in (("items", ITEMS), ("plan", PLAN), ("board", {"meta": META})):
            os.makedirs(os.path.join(d, "dump", name))
            for k, v in docs.items():
                json.dump(v, open(os.path.join(d, "dump", name, k + ".json"), "w"))
        r = subprocess.run(["node", os.path.join(PAGE_DIR, "render_merge.cjs"), os.path.join(PAGE_DIR, "board.html"), os.path.join(d, "dump"),
                            os.path.join(d, "out"), "test"], capture_output=True, text=True, timeout=300,
                           env=dict(os.environ, PLAYWRIGHT_CORE=PLAYWRIGHT))
        if r.returncode == 2 and "No Chromium found" in r.stderr:
            self.skipTest("no Chromium found")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("all checks hold", r.stdout); self.assertIn("page errors: []", r.stdout)
