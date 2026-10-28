"""The Approvals panel patch and the helper that raises an approval. Anchors are exact; a second apply is refused;
the helper refuses an image id that is not a 32 character hex id, because the page builds a /_blob/ address from it."""
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
from brain import approvals as ra  # noqa: E402
from brain import approvals_patch as ap  # noqa: E402

PAGE = os.path.join(HERE, "..", "assets", "board", "board.html")
BRAIN = os.path.join(HERE, "..", "scripts", "brain.py")
# The page and the helper both ship inside the pack (VH-584), so these checks run in a copy of the pack alone, the mutation harness's
# included. The page checks are still guarded on the page, so a pack trimmed of its assets says why it skipped rather than erroring.
SKIP = unittest.skipUnless(os.path.exists(PAGE), "the board page is not in this copy of the pack")


def bare_page():
    """The page as it was before the panel: the committed source with the panel taken out again."""
    with open(PAGE, encoding="utf-8") as f:
        h = f.read()
    css = h[h.index("/* APPROVALS (owner, 2026-10-05)") - 1:h.index("</style>")]
    h = h.replace(css, "", 1)
    s, e = h.index('  <section class="panel appr"'), h.index('  <section class="panel hero"')
    h = h[:s] + h[e:]
    s, e = h.index('<dialog class="lb"'), h.index('<div class="tip" id="tip" hidden></div>')
    h = h[:s] + h[e:]
    h = h.replace("renderDecQ(); renderAppr(); }); }", "renderDecQ(); }); }", 1)
    s, e = h.index("  " + ap.BEGIN), h.index("  setInterval(() => { if (!document.hidden) render(); }, 60000);")
    return h[:s] + h[e:]


@SKIP
class Patch(unittest.TestCase):
    def test_the_committed_page_is_the_patched_bare_page(self):
        with open(PAGE, encoding="utf-8") as f:
            page = f.read()
        self.assertTrue(ap.has(page))
        self.assertEqual(ap.apply(bare_page()), page)       # the source file is exactly what apply() makes

    def test_apply_adds_the_panel_the_dialog_and_the_hook(self):
        out = ap.apply(bare_page())
        for needle in ('id="apprPanel"', 'id="lbDlg"', "renderAppr(); }); }", "function apprAnswer", "APPR_UNDO_MS = 10000"):
            self.assertEqual(out.count(needle), 1, needle)

    def test_a_second_apply_is_refused(self):
        with self.assertRaises(ValueError):
            ap.apply(ap.apply(bare_page()))
        marked = bare_page().replace("</style>", "/*APPROVALS:BEGIN*/</style>", 1)     # the marker, with every anchor still there once
        with self.assertRaisesRegex(ValueError, "already has the Approvals panel"):
            ap.apply(marked)

    def test_a_missing_or_repeated_anchor_is_refused_and_nothing_is_written(self):
        base = bare_page()
        for anchor in ('<section class="panel hero" aria-label="Current release">', "renderThreads(); renderDecQ(); }); }"):
            with self.assertRaises(ValueError):
                ap.apply(base.replace(anchor, "", 1))
            with self.assertRaises(ValueError):
                ap.apply(base.replace(anchor, anchor + anchor, 1))

    def test_the_page_only_trusts_a_32_hex_image_id(self):
        self.assertIn('/^[0-9a-f]{32}$/.test(String(im?.id || ""))', ap.JS)


class Raise(unittest.TestCase):
    ID = "0123456789abcdef0123456789abcdef"

    def test_a_screenshot_approval(self):
        out = ra.build("Approve the door?", "Rendered at 1280.", [{"id": self.ID, "alt": "Desktop", "caption": "Desktop 1280"}],
                       [{"label": "Approve as drawn", "detail": "Built next.", "recommended": True}, {"label": "Move it"}])
        self.assertEqual(out["state"], "input")
        self.assertEqual(out["decision"]["kind"], "screenshot")
        self.assertIsNone(out["decisionAnswer"])
        self.assertEqual(out["decision"]["images"][0]["id"], self.ID)
        self.assertTrue(out["decision"]["options"][0]["recommended"])

    def test_a_plain_decision_has_no_images_and_no_kind(self):
        out = ra.build("Keep it?", "", [], [{"label": "Yes"}, {"label": "No"}])
        self.assertNotIn("images", out["decision"])
        self.assertNotIn("kind", out["decision"])

    def test_refuses_what_the_page_would_misread(self):
        for bad in ("../../x", self.ID.upper(), self.ID[:-1], ""):
            with self.assertRaises(ValueError):
                ra.build("q?", "", [{"id": bad}], [{"label": "Yes"}])
        with self.assertRaises(ValueError):
            ra.build("q?", "", [], [{"label": "A", "recommended": True}, {"label": "B", "recommended": True}])
        with self.assertRaises(ValueError):
            ra.build("q?", "", [], [])
        with self.assertRaises(ValueError):
            ra.build("q?", "", [{"id": self.ID}] * 9, [{"label": "Yes"}])

    def test_the_command_line_prints_json_and_fails_cleanly(self):
        ok = subprocess.run([sys.executable, BRAIN, "approval", "--question", "Keep it?", "--option", "Yes|Fine.|rec", "--option", "No"], capture_output=True, text=True)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        bad = subprocess.run([sys.executable, BRAIN, "approval", "--question", "Q?", "--image", "nothex:a:b", "--option", "Yes"], capture_output=True, text=True)
        self.assertEqual(bad.returncode, 2)


if __name__ == "__main__":
    unittest.main()
