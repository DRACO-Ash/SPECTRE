import ast, os, re, sys, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))


def stated(pattern):
    m = re.search(pattern, open(os.path.join(ROOT, "SKILL.md")).read())
    assert m, f"SKILL.md no longer states {pattern!r}"
    return [int(g) for g in m.groups()]


class Counts(unittest.TestCase):
    """SKILL.md states how many tests and mutations there are (VH-464). It went stale once (30 and 25 against 43 and 29), so
    a count that drifts now fails here instead of being found by a reader."""

    def test_the_stated_test_count_is_the_real_one(self):
        real = unittest.defaultTestLoader.discover(HERE).countTestCases()
        self.assertEqual(stated(r"runs (\d+) tests")[0], real, "update the count in SKILL.md, section Tests and proof")

    def test_the_stated_mutation_count_is_the_real_one(self):
        tree = ast.parse(open(os.path.join(HERE, "mutations.py")).read())
        rows = [n.value for n in ast.walk(tree) if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "M" for t in n.targets)]
        self.assertEqual(len(rows), 1)
        real = len(rows[0].elts)
        a, b = stated(r"\((\d+) of (\d+) caught")
        self.assertEqual((a, b), (real, real), "update the mutation count in SKILL.md, section Tests and proof")


if __name__ == "__main__":
    unittest.main()


class PlanOutput(unittest.TestCase):
    def test_the_text_plan_shows_the_tooling_items_as_well_as_the_releases(self):
        import json, subprocess, tempfile
        d = tempfile.mkdtemp()
        cfg = {"schema": 1, "project": {"name": "T", "ref_prefix": "T-"}, "releases": {"start": "V1.0", "floor_min": 100, "cap_min": 600, "overhead_min": 0, "pace": 1.0, "target_min": 600},
               "gates": [], "people": [], "agents": {"max_concurrent": 1}}
        json.dump(cfg, open(os.path.join(d, "c.json"), "w"))
        json.dump([{"ref": "T-1", "minutes": 60, "priority": "high", "files": ["src/a.js"]},
                   {"ref": "T-2", "minutes": 45, "priority": "high", "track": "tooling", "files": ["tools/x.py"]}], open(os.path.join(d, "i.json"), "w"))
        r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "brain.py"), "plan", "--config", os.path.join(d, "c.json"), "--items", os.path.join(d, "i.json")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("tooling: 1 items, 45 priced min", r.stdout); self.assertIn("T-2", r.stdout)


class WorkedExample(unittest.TestCase):
    """The worked example (VH-471) carries files on some items, so it exercises lanes: items sharing a file share a lane."""

    def test_the_example_has_shared_files_and_the_plan_keeps_those_items_in_one_lane(self):
        import json
        sys.path.insert(0, ROOT)
        from brain.api import run
        items = json.load(open(os.path.join(ROOT, "assets", "example", "items.json")))
        cfg = json.load(open(os.path.join(ROOT, "assets", "example", "config.json")))
        by_file = {}
        for it in items:
            for f in it.get("files") or []:
                by_file.setdefault(f, []).append(it["ref"])
        shared = {f: refs for f, refs in by_file.items() if len(refs) > 1}
        self.assertGreaterEqual(len(shared), 2, "the example must have at least two files shared by two items, or it proves nothing about lanes")
        res = run(cfg, items)
        for f, refs in shared.items():
            for rel in res["releases"]:
                lane_of = {r: n for n, lane in enumerate(rel["lanes"]) for r in lane["refs"]}
                present = [r for r in refs if r in lane_of]
                if len(present) > 1:
                    self.assertEqual(len({lane_of[r] for r in present}), 1, f"{f}: {present} must share a lane in {rel['name']}")
