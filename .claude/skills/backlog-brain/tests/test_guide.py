"""The "how to use me" guide: its wording rules, its steps, and that the board page and the pack agree with it.

Run with the rest: python3 scripts/brain.py selftest
"""
import json, os, re, sys, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
from brain.board import PAGE_DEFAULTS, fill_guide
from brain.guide import load_guide, render_text
from brain.page_patch import apply, embed, embedded, BEGIN

# The board guide carries settings tokens (VH-584), so its wording is checked as it reads: filled with this board's values
# and with another project's, which has no store, a short budget and its own ref prefix.
OTHER = dict(PAGE_DEFAULTS, refPrefix="HW-", budget={"floorMin": 480, "capMin": 600}, overheadMin=90, store=None, rounds=None,
             source={"name": "the build log", "detail": "", "command": "", "onRelease": ""})


def filled(guide, settings=None):
    return {aud: fill_guide(g, settings) for aud, g in guide.items()}

PAGE = os.path.abspath(os.path.join(HERE, "..", "assets", "board", "board.html"))
BANNED = ["seamless", "leverage", "delve", "robust", "utilise", "utilize", "streamline", "empower", "unlock", "cutting-edge",
          "holistic", "synergy", "revolutionary", "effortless", "dive into", "navigate", "landscape", "tapestry",
          "it's important to note", "please note", "at the end of the day", "in today's", "game-changing", "supercharge"]
US = ["color", "behavior", "organiz", "prioritiz", "analyz", "center", "favorite", "optimiz", "recogniz", "license "]
NUMBER_WORDS = r"\b(five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|twenty)\b"


def texts(guide):
    for aud, g in guide.items():
        yield aud, "title", g["title"]
        yield aud, "intro", g["intro"]
        for w in g.get("who", []):
            yield aud, "who", w
        for j in g["jobs"]:
            yield aud, j["id"] + " title", j["title"]
            for s in j["steps"]:
                yield aud, j["id"], s


class Wording(unittest.TestCase):
    def setUp(self):
        self.g = filled(load_guide())

    def test_another_projects_guide_keeps_the_same_rules(self):
        other = filled(load_guide(), OTHER)
        for aud, where, t in texts(other):
            self.assertNotRegex(t, r"[{}]", f"{aud}/{where} has a token left unfilled")
            self.assertNotRegex(t, NUMBER_WORDS, f"{aud}/{where} spells out a number of 5 or more")
            self.assertNotIn("+", t, f"{aud}/{where} has a plus sign")
            for sentence in re.split(r"(?<=[.!?])\s+", t):
                self.assertLessEqual(len(sentence.split()), 38, f"{aud}/{where}: a sentence over 38 words")
        self.assertNotIn("upload", [j["id"] for j in other["board"]["jobs"]])

    def test_both_audiences_exist_and_have_jobs(self):
        self.assertEqual(sorted(self.g), ["board", "pack"])
        for g in self.g.values():
            self.assertTrue(g["jobs"])
            ids = [j["id"] for j in g["jobs"]]
            self.assertEqual(len(ids), len(set(ids)), "a job id is repeated")

    def test_no_ai_cliches(self):
        for aud, where, t in texts(self.g):
            for w in BANNED:
                self.assertNotIn(w, t.lower(), f"{aud}/{where} uses '{w}'")

    def test_house_rules(self):
        for aud, where, t in texts(self.g):
            self.assertNotRegex(t, "[—–]", f"{aud}/{where} has a long dash")
            self.assertNotRegex(t, r"(^|\s)--(\s|$)", f"{aud}/{where} has a double dash")
            self.assertNotIn("+", t, f"{aud}/{where} has a plus sign")
            self.assertNotRegex(t, NUMBER_WORDS, f"{aud}/{where} spells out a number of 5 or more")
            self.assertFalse(t.lstrip().startswith("- "), f"{aud}/{where} starts with a dash bullet")
            for u in US:
                self.assertNotIn(u, t.lower(), f"{aud}/{where} uses a US spelling ('{u}')")

    def test_plain_short_sentences(self):
        for aud, where, t in texts(self.g):
            for sentence in re.split(r"(?<=[.!?])\s+", t):
                self.assertLessEqual(len(sentence.split()), 38, f"{aud}/{where}: a sentence over 38 words: {sentence[:50]}")

    def test_each_job_is_a_short_list_of_actions(self):
        for aud, g in self.g.items():
            for j in g["jobs"]:
                self.assertTrue(2 <= len(j["steps"]) <= 5, f"{aud}/{j['id']} has {len(j['steps'])} steps")
                for s in j["steps"]:
                    self.assertGreaterEqual(len(s.split()), 3)

    def test_every_listed_control_is_used_in_a_step(self):
        for j in self.g["board"]["jobs"]:
            body = " ".join(j["steps"])
            for c in j.get("controls", []):
                self.assertIn(c, body, f"{j['id']} lists '{c}' but no step uses it")

    def test_text_render(self):
        out = render_text(self.g, "pack")
        self.assertIn("How to use Backlog Brain", out)
        self.assertIn("1. Copy the backlog-brain folder", out)
        self.assertIn("How to use me", render_text(self.g, "board"))
        board = render_text(load_guide(), "board")                # the tokens are filled, from this board's values when none are given
        self.assertIn("about 12 to 14 hours", board); self.assertNotIn("{", board)
        self.assertIn("like HW-318", render_text(load_guide(), "board", OTHER))
        with self.assertRaises(ValueError):
            render_text(self.g, "nobody")


@unittest.skipUnless(os.path.exists(PAGE), "the board page is not in this copy of the pack, so there is nothing to check it against")
class AgainstThePage(unittest.TestCase):
    def setUp(self):
        self.html = open(PAGE, encoding="utf-8").read()
        self.g = filled(load_guide())

    def test_page_carries_the_feature(self):
        self.assertIn('id="howBtn"', self.html)
        self.assertIn('id="howDlg"', self.html)

    def test_every_control_named_in_the_guide_is_on_the_page(self):
        # the page's own source minus the embedded guide, so the guide cannot vouch for itself
        page = re.sub(re.escape(BEGIN) + r".*?/\*HOWTO:END\*/", "", self.html, flags=re.S)
        for j in self.g["board"]["jobs"]:
            for c in j.get("controls", []):
                self.assertIn(c, page, f"the guide names '{c}' in '{j['title']}' but the page has no such label")

    def test_page_and_source_hold_the_same_text(self):
        self.assertEqual(embedded(self.html), load_guide()["board"], "the page's copy of the guide is out of date: run page_patch.embed")


class PatchMechanics(unittest.TestCase):
    PAGE_STUB = ('dialog.dec::backdrop{background:rgba(5,12,24,.55)}\n<button class="btn" id="decQBtn" type="button" hidden>x</button>\n'
                 '<div class="tip" id="tip" hidden></div>\n  /*SETTINGS:BEGIN*/ /*SETTINGS:END*/\n  $("decQBtn").addEventListener("click", () => {')

    def test_apply_then_embed(self):
        g = load_guide()
        out = apply(self.PAGE_STUB, g)
        self.assertEqual(embedded(out), g["board"])
        g2 = json.loads(json.dumps(g)); g2["board"]["title"] = "Changed"
        self.assertEqual(embedded(embed(out, g2))["title"], "Changed")

    def test_refuses_a_missing_or_repeated_anchor_and_a_second_apply(self):
        with self.assertRaises(ValueError):
            apply("<html></html>")
        with self.assertRaises(ValueError):
            apply(self.PAGE_STUB + self.PAGE_STUB)
        with self.assertRaises(ValueError):
            apply(apply(self.PAGE_STUB))
        with self.assertRaises(ValueError):
            embed(self.PAGE_STUB)
        with self.assertRaisesRegex(ValueError, "no settings block"):          # the guide's tokens need the page's settings
            apply(self.PAGE_STUB.replace("/*SETTINGS:BEGIN*/ /*SETTINGS:END*/", ""))


if __name__ == "__main__":
    unittest.main()
