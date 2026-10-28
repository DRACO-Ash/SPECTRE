import json, os, subprocess, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from brain.dupes import find, family
from brain.evidence import cited, missing

BRAIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts", "brain.py")


def it(task, note="", **kw):
    d = {"task": task, "note": note, "state": "open"}
    d.update(kw)
    return d


ITEMS = {"T-1": it("Retire the legacy export writer and its CSV shape"), "T-2": it("Retire the legacy export writer and its CSV format"),
         "T-3": it("Show the globe in dark mode with a restyle on change"), "T-4": it("Rate limit the login route by address"),
         "T-5": it("Print the invoice summary table in landscape")}


class Dupes(unittest.TestCase):
    def test_two_tasks_that_read_alike_are_a_pair_and_unlike_ones_are_not(self):
        pairs = find(ITEMS, 0.55)
        self.assertEqual([(a, b) for _, a, b in pairs], [("T-1", "T-2")], pairs)

    def test_the_threshold_decides(self):
        self.assertEqual(find(ITEMS, 0.99), [])
        self.assertTrue(find(ITEMS, 0.1))

    def test_a_split_inside_one_family_is_not_a_duplicate(self):
        fam = {"T-9-A": it("Retire the legacy export writer and its CSV shape"), "T-9-B": it("Retire the legacy export writer and its CSV shape")}
        self.assertEqual(find(fam, 0.1), [])
        self.assertEqual((family("T-9-A"), family("VH-009-Q1"), family("x")), ("T-9", "VH-009", "x"))
        par = {"T-1": it("Retire the legacy export writer and its CSV shape", parent="P"), "T-2": it("Retire the legacy export writer and its CSV shape", parent="P")}
        self.assertEqual(find(par, 0.1), [])

    def test_a_recorded_relationship_is_not_reported(self):
        rec = dict(ITEMS); rec["T-2"] = it("Retire the legacy export writer and its CSV format", "Supersedes T-1.")
        self.assertEqual(find(rec, 0.55), [])

    def test_done_and_removed_tasks_are_not_compared(self):
        d = dict(ITEMS); d["T-2"] = it("Retire the legacy export writer and its CSV format", state="built")
        self.assertEqual(find(d, 0.55), [])
        d["T-2"] = it("Retire the legacy export writer and its CSV format", state="removed")
        self.assertEqual(find(d, 0.55), [])

    def test_the_title_counts_more_than_a_shared_template_note(self):
        tpl = "Raised by delivery in its status entry for the second wave, for the backlog to shape; none built."
        pairs = find({"T-1": it("Show the globe in dark mode", tpl), "T-2": it("Rate limit the login route by address", tpl), "T-3": it("Print the invoice table in landscape", tpl)}, 0.55)
        self.assertEqual(pairs, [])
        # Shared by 2 of 5, so the template's words are rare enough to count: with the title once the pair scores 0.455, with it
        # three times 0.085 (measured 2026-10-07), so 0.35 tells the two apart.
        note = "Raised by delivery in its report of 2026-10-05 about the board, the gate rounds and the coverage each release costs."
        five = {"T-1": it("Retire the legacy export writer", note), "T-2": it("Add a keyboard shortcut to the map", note),
                "T-3": it("Price the deploy gate by stage"), "T-4": it("Show the grade colours on the vendor card"), "T-5": it("Name each record in the area digest")}
        self.assertEqual(find(five, 0.35), [])


class Evidence(unittest.TestCase):
    def tree(self):
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "src")); open(os.path.join(d, "src", "real.js"), "w").write("x")
        return d

    def test_a_cited_path_that_is_not_there_is_reported_and_one_that_is_there_is_not(self):
        items = {"T-1": it("Fix src/real.js"), "T-2": it("Fix src/gone.js and the line at src/real.js:12")}
        self.assertEqual(missing(items, self.tree()), [("T-2", "src/gone.js")])

    def test_a_path_in_any_given_tree_counts(self):
        a, b = self.tree(), tempfile.mkdtemp()
        os.makedirs(os.path.join(b, "docs")); open(os.path.join(b, "docs", "x.md"), "w").write("x")
        self.assertEqual(missing({"T-1": it("See docs/x.md")}, [a, b]), [])
        self.assertEqual(missing({"T-1": it("See docs/x.md")}, a), [("T-1", "docs/x.md")])

    def test_a_path_meant_to_be_new_or_already_gone_is_not_reported(self):
        for note in ("Create a new file src/fresh.js for it", "Planned: add src/fresh.js", "The module src/fresh.js was retired", "src/fresh.js does not exist any more"):
            self.assertEqual(missing({"T-1": it("x", note)}, self.tree()), [], note)

    def test_wildcards_placeholders_and_done_tasks_are_skipped(self):
        d = self.tree()
        self.assertEqual(missing({"T-1": it("x", "all of src/*.js and docs/<name>.md")}, d), [])
        self.assertEqual(missing({"T-1": it("Fix src/gone.js", state="built")}, d), [])

    def test_a_double_extension_and_trailing_punctuation_are_read_whole(self):
        self.assertEqual(cited(it("See test/styles-tokens.test.js, and docs/a.md.")), ["test/styles-tokens.test.js", "docs/a.md"])


class Commands(unittest.TestCase):
    def cli(self, *a):
        return subprocess.run([sys.executable, BRAIN, *a], capture_output=True, text=True)

    def test_dupes_prints_the_pair_and_exits_one_and_a_clean_board_exits_zero(self):
        d = tempfile.mkdtemp(); p = os.path.join(d, "i.json"); json.dump(ITEMS, open(p, "w"))
        r = self.cli("dupes", "--items", p)
        self.assertEqual(r.returncode, 1, r.stdout); self.assertIn("T-1  T-2", r.stdout)
        json.dump({"T-4": ITEMS["T-4"], "T-5": ITEMS["T-5"]}, open(p, "w"))
        self.assertEqual(self.cli("dupes", "--items", p).returncode, 0)
        self.assertEqual(self.cli("dupes", "--items", os.path.join(d, "none.json")).returncode, 2)

    def test_evidence_reads_a_dump_folder_and_a_tree(self):
        d = tempfile.mkdtemp(); os.makedirs(os.path.join(d, "dump"))
        json.dump({"data": it("Fix src/gone.js")}, open(os.path.join(d, "dump", "T-1.json"), "w"))
        r = self.cli("evidence", "--items", os.path.join(d, "dump"), "--repo", d)
        self.assertEqual(r.returncode, 1, r.stdout); self.assertIn("T-1: cites src/gone.js", r.stdout)
        self.assertEqual(self.cli("evidence", "--items", os.path.join(d, "dump"), "--repo", os.path.join(d, "nope")).returncode, 2)


if __name__ == "__main__":
    unittest.main()
