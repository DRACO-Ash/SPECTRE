import copy, json, os, shutil, subprocess, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from brain.bundle import export_board, import_board, write_dump, read_dump, save

BRAIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts", "brain.py")
COL = {"items": {"T-1": {"state": "open", "release": "r-a", "minutes": 30, "note": "", "time": "30m"}}, "plan": {"r-a": {"name": "R1.0"}}}
NOW = "2026-10-06T20:00:00Z"


def mkdump(col=COL):
    d = tempfile.mkdtemp()
    write_dump(d, col)
    return d


class Bundle(unittest.TestCase):
    def test_a_board_survives_the_round_trip_unchanged(self):
        back, problems = import_board(export_board(COL, NOW))
        self.assertEqual((back, problems), (COL, []))

    def test_every_kind_of_damage_is_refused_whole(self):
        for name, damage in (("schema", lambda b: b.update(schema=9)), ("count", lambda b: b["counts"].update(items=5)),
                             ("checksum", lambda b: b["collections"]["items"]["T-1"].update(minutes=31)),
                             ("empty", lambda b: b.update(collections={})), ("shape", lambda b: b["collections"].update(items=[1]))):
            b = copy.deepcopy(export_board(COL, NOW)); damage(b)
            back, problems = import_board(b)
            self.assertEqual(back, {}, name); self.assertTrue(problems, name)
        self.assertEqual(import_board("x")[0], {})

    def test_a_dump_reads_back_as_what_was_written_and_a_missing_collection_is_not_invented(self):
        d = mkdump()
        self.assertEqual(read_dump(d), COL)
        self.assertNotIn("gates", read_dump(d))

    def test_writing_a_dump_never_overwrites(self):
        d = mkdump()
        with self.assertRaises(FileExistsError):
            write_dump(d, COL)

    def test_a_refused_write_writes_nothing_at_all(self):
        # Only the last collection is there already: every collection is checked before any is written, so the first is not
        # left half-imported beside it.
        d = tempfile.mkdtemp(); last = list(COL)[-1]; os.makedirs(os.path.join(d, last))
        with self.assertRaises(FileExistsError):
            write_dump(d, COL)
        self.assertEqual(os.listdir(d), [last])

    def test_a_failed_save_leaves_the_old_file_whole(self):
        d = tempfile.mkdtemp(); p = os.path.join(d, "b.json")
        save(p, {"a": 1})
        with self.assertRaises(TypeError):
            save(p, {"a": object()})
        self.assertEqual(json.load(open(p)), {"a": 1}); self.assertEqual([f for f in os.listdir(d) if f.endswith(".tmp")], [])


class Commands(unittest.TestCase):
    def cli(self, *args):
        return subprocess.run([sys.executable, BRAIN, *args], capture_output=True, text=True)

    def test_export_then_import_into_an_empty_folder_reproduces_the_dump_and_refuses_a_second_import(self):
        d = mkdump(); out = os.path.join(tempfile.mkdtemp(), "board.json"); back = os.path.join(tempfile.mkdtemp(), "back")
        r = self.cli("export", "--dump", d, "--out", out, "--now", NOW)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.cli("import", "--file", out, "--out", back).returncode, 0)
        self.assertEqual(read_dump(back), COL)
        self.assertEqual(self.cli("import", "--file", out, "--out", back).returncode, 2)          # it will not overwrite

    def test_a_damaged_file_is_refused(self):
        d = mkdump(); out = os.path.join(tempfile.mkdtemp(), "board.json")
        self.cli("export", "--dump", d, "--out", out, "--now", NOW)
        b = json.load(open(out)); b["collections"]["items"]["T-1"]["minutes"] = 99; json.dump(b, open(out, "w"))
        r = self.cli("import", "--file", out, "--out", os.path.join(tempfile.mkdtemp(), "x"))
        self.assertEqual(r.returncode, 2); self.assertIn("checksum", r.stdout)

    def test_check_is_clean_on_a_fresh_dump_and_fails_on_a_planted_fault(self):
        r = self.cli("check", "--dump", mkdump(), "--now", NOW)
        self.assertEqual(r.returncode, 0, r.stdout); self.assertIn("R1.0: 1 open, 30 priced minutes", r.stdout)
        bad = {"items": {"T-1": dict(COL["items"]["T-1"], time="45m: x")}, "plan": COL["plan"]}
        r = self.cli("check", "--dump", mkdump(bad), "--now", NOW)
        self.assertEqual(r.returncode, 1); self.assertIn("FAIL T-1: time field", r.stdout)

    def test_a_missing_store_reads_the_export_and_says_so_with_exit_three(self):
        d = mkdump(); out = os.path.join(tempfile.mkdtemp(), "board.json")
        self.cli("export", "--dump", d, "--out", out, "--now", NOW)
        r = self.cli("check", "--dump", os.path.join(tempfile.mkdtemp(), "gone"), "--fallback", out, "--now", "2026-10-06T20:05:00Z")
        self.assertEqual(r.returncode, 3, r.stdout); self.assertIn("DEGRADED", r.stdout)
        r = self.cli("check", "--dump", os.path.join(tempfile.mkdtemp(), "gone"), "--fallback", out, "--now", "2026-10-06T21:00:00Z")
        self.assertEqual(r.returncode, 1); self.assertIn("STALE DUMP", r.stdout)                  # an old export still fails the freshness rule
        self.assertEqual(self.cli("check", "--dump", os.path.join(tempfile.mkdtemp(), "gone")).returncode, 2)   # no fallback, no read

    def test_selfcheck_passes_on_the_pack_itself(self):
        r = self.cli("selfcheck")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr); self.assertIn("survives export and import", r.stdout)
        if os.environ.get("BRAIN_SELFCHECK_RUNNING"):                                          # inside a self-check it does not recurse
            self.assertIn("already inside a self-check", r.stdout)
        else:
            self.assertRegex(r.stdout, r"the pack's own tests: \d+ run, 0 failed, \d+ skipped")  # a check that skipped is never read as a pass

    def test_the_header_and_the_settings_travel_and_the_standing_rules_do_not(self):
        col = dict(COL, board={"meta": {"updatedAt": "2026-10-06T19:00:00Z"}, "settings": {"schema": 1}, "standing": {"rule": "this project only"}})
        d = mkdump(col); t = tempfile.mkdtemp(); out = os.path.join(t, "board.json")
        for x in (d, t):
            self.addCleanup(shutil.rmtree, x, True)
        self.assertEqual(self.cli("export", "--dump", d, "--out", out, "--now", NOW).returncode, 0)
        self.assertEqual(sorted(json.load(open(out))["collections"]["board"]), ["meta", "settings"])
        self.assertNotIn("standing", read_dump(d).get("board", {}))

    def test_check_reads_the_header_from_the_dump(self):
        old, fresh = mkdump(dict(COL, board={"meta": {"updatedAt": "2026-10-06T17:00:00Z"}})), mkdump(dict(COL, board={"meta": {"updatedAt": "2026-10-06T19:30:00Z"}}))
        for x in (old, fresh):
            self.addCleanup(shutil.rmtree, x, True)
        r = self.cli("check", "--dump", old, "--now", NOW)
        self.assertEqual(r.returncode, 1, r.stdout); self.assertIn("BOARD HEADER STALE", r.stdout)
        self.assertEqual(self.cli("check", "--dump", fresh, "--now", NOW).returncode, 0)


if __name__ == "__main__":
    unittest.main()
