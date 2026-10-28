"""VH-377, second half: the supersession record (C) and the duplicate (A) and evidence (D) checks wired into `brain.py check`, so the
hourly guard runs them rather than only their own tests. Revised after the change's independent review: the evidence check reads
the working tree and every fetched branch for what it added, and these tests drive the path the hourly guard really takes (no
--repo, the pack inside a git repository). Git here runs with the host's configuration and GIT_* variables shut out, and cannot
search above the temp folder, so a signer, a hook or an enclosing repository cannot change a result."""
import json, os, shutil, subprocess, sys, tempfile, unittest
from unittest import mock
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from brain.dupes import find
from brain.evidence import cited, git_trees, missing
from brain.guard import check_duplicates, check_evidence, check_superseded

PACK = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
BRAIN = os.path.join(PACK, "scripts", "brain.py")
SAME = "Retire the legacy export writer and its CSV shape"
GIT_ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
GIT_ENV.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_CEILING_DIRECTORIES=os.path.realpath(tempfile.gettempdir()),
               PYTHONDONTWRITEBYTECODE="1")


def it(task="A task", note="", **kw):
    d = {"task": task, "note": note, "state": "open"}
    d.update(kw)
    return d


def tmp(case):
    d = tempfile.mkdtemp()
    case.addCleanup(shutil.rmtree, d, True)
    return d


def git(d, *a):
    return subprocess.run(["git", "-C", d, "-c", "commit.gpgsign=false", "-c", "core.hooksPath=" + os.devnull, "-c", "user.email=t@t",
                           "-c", "user.name=t", *a], capture_output=True, text=True, check=True, env=GIT_ENV, timeout=30, input="").stdout.strip()


def write(d, rel, text="x"):
    p = os.path.join(d, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w").write(text)


def git_repo(case, extra=()):
    """HEAD (branch base) holds src/real.js and has deleted src/old.js. Fetched refs: origin/claude/side ADDED src/side.js and
    src/café.js; origin/feature/x ADDED src/feat.js; origin/claude/old is base before the deletion, merged, so it added nothing;
    origin/claude/stray shares no history with HEAD, so it cannot be read. `extra` files are committed on base first."""
    d = tmp(case)
    git(d, "init", "-q", "-b", "base")
    for rel in ("src/real.js", "src/old.js", *extra):
        write(d, rel)
    git(d, "add", "-A"); git(d, "commit", "-qm", "base")
    git(d, "update-ref", "refs/remotes/origin/claude/old", "base")
    git(d, "checkout", "-qb", "side"); write(d, "src/side.js"); write(d, "src/café.js"); git(d, "add", "-A"); git(d, "commit", "-qm", "side")
    git(d, "update-ref", "refs/remotes/origin/claude/side", "side")
    git(d, "checkout", "-q", "base"); git(d, "checkout", "-qb", "feat"); write(d, "src/feat.js"); git(d, "add", "-A"); git(d, "commit", "-qm", "feat")
    git(d, "update-ref", "refs/remotes/origin/feature/x", "feat")
    git(d, "checkout", "-q", "base"); git(d, "rm", "-q", "src/old.js"); git(d, "commit", "-qm", "drop old")
    stray = git(d, "commit-tree", git(d, "mktree"), "-m", "stray")
    git(d, "update-ref", "refs/remotes/origin/claude/stray", stray)
    return d


class Superseded(unittest.TestCase):
    def test_an_open_task_carrying_superseded_by_fails_and_a_closed_one_does_not(self):
        f = check_superseded({"T-1": it(supersededBy="T-2"), "T-2": it(state="built")})
        self.assertEqual(len(f), 1, f); self.assertIn("T-1: superseded by T-2 but still open", f[0])
        self.assertEqual(check_superseded({"T-1": it(state="closed", supersededBy="T-2"), "T-2": it(state="built")}), [])
        self.assertEqual(check_superseded({"T-1": it()}), [])

    def test_a_superseded_by_ref_the_board_does_not_hold_fails_and_a_sentence_does_not(self):
        f = check_superseded({"T-1": it(state="closed", supersededBy="T-9")})
        self.assertEqual(f, ["T-1: supersededBy names T-9, which is not on the board"])
        self.assertEqual(check_superseded({"T-1": it(state="closed", supersededBy="the owner's ruling of 2026-10-05")}), [])


class Declared(unittest.TestCase):
    def test_a_pair_declared_distinct_or_related_is_not_reported_either_way_round(self):
        base = {"T-1": it(SAME), "T-2": it(SAME)}
        self.assertEqual(len(find(base, 0.55)), 1)
        for key in ("distinctFrom", "relatesTo"):
            for holder, other in (("T-1", "T-2"), ("T-2", "T-1")):
                for value in (other, [other]):
                    items = {"T-1": it(SAME), "T-2": it(SAME)}
                    items[holder][key] = value
                    self.assertEqual(find(items, 0.55), [], (key, holder, value))

    def test_a_declaration_may_be_a_comma_list_in_any_case_and_padding(self):
        for value in ("T-9, t-2", " t-2 ", ["T-9", " t-2"]):
            self.assertEqual(find({"T-1": it(SAME, distinctFrom=value), "T-2": it(SAME)}, 0.55), [], value)
        self.assertEqual(len(find({"T-1": it(SAME, distinctFrom="T-9, T-22"), "T-2": it(SAME)}, 0.55)), 1)
        # A board ref may hold lower case ("VH-950 part 2"), so the ref being looked for is folded too, not only the declaration.
        self.assertEqual(find({"T-1": it(SAME, distinctFrom="T-2 PART 2"), "T-2 part 2": it(SAME)}, 0.55), [])

    def test_the_duplicate_check_reads_its_threshold_from_the_settings(self):
        items = {"T-1": it(SAME), "T-2": it("Retire the legacy export writer and its CSV format"),
                 "T-3": it("Add a keyboard shortcut to the map"), "T-4": it("Price the deploy gate by stage"),
                 "T-5": it("Show the grade colours on the vendor card")}
        self.assertEqual(len(check_duplicates(items)), 1)
        self.assertIn("T-1 and T-2 read like the same job", check_duplicates(items)[0])
        self.assertEqual(check_duplicates(items, {"guard": {"dupes_threshold": 0.999}}), [])


class Evidence(unittest.TestCase):
    def setUp(self):
        p = mock.patch.dict(os.environ, GIT_ENV, clear=True)
        p.start(); self.addCleanup(p.stop)

    def test_head_counts_whole_and_another_branch_counts_for_what_it_added(self):
        d = git_repo(self)
        g = git_trees(d)
        self.assertEqual([r for r, _ in g["trees"]], ["HEAD", "refs/remotes/origin/claude/old", "refs/remotes/origin/claude/side",
                                                      "refs/remotes/origin/feature/x"])
        cites = {"T-1": it("Fix src/side.js"), "T-2": it("Fix src/gone.js"), "T-3": it("Fix src/real.js"), "T-4": it("Fix src/feat.js"),
                 "T-5": it("Fix src/old.js")}
        self.assertEqual(missing(cites, [], [t for _, t in g["trees"]]), [("T-2", "src/gone.js"), ("T-5", "src/old.js")])

    def test_a_merged_branch_does_not_keep_a_deleted_file_alive(self):
        g = git_trees(git_repo(self))
        self.assertEqual(dict(g["trees"])["refs/remotes/origin/claude/old"], set())
        self.assertNotIn("src/old.js", set().union(*[t for _, t in g["trees"]]))

    def test_the_patterns_choose_which_branches_count(self):
        g = git_trees(git_repo(self), ["refs/remotes/origin/claude/"])
        self.assertNotIn("refs/remotes/origin/feature/x", dict(g["trees"]))
        self.assertEqual(missing({"T-1": it("Fix src/feat.js")}, [], [t for _, t in g["trees"]]), [("T-1", "src/feat.js")])

    def test_a_branch_that_cannot_be_read_is_reported_never_guessed(self):
        self.assertEqual(git_trees(git_repo(self))["unread"], ["refs/remotes/origin/claude/stray"])

    def test_a_name_git_would_quote_reads_as_itself(self):
        g = git_trees(git_repo(self))
        self.assertIn("src/café.js", dict(g["trees"])["refs/remotes/origin/claude/side"])
        self.assertEqual(missing({"T-1": it("Fix src/café.js")}, [], [t for _, t in g["trees"]]), [])

    def test_paths_are_read_from_the_root_even_from_a_subfolder(self):
        d = git_repo(self)
        g = git_trees(os.path.join(d, "src"))
        self.assertIn("src/real.js", g["trees"][0][1]); self.assertEqual(os.path.realpath(g["top"]), os.path.realpath(d))

    def test_not_a_repository_gives_no_trees(self):
        self.assertEqual(git_trees(tmp(self)), {"trees": [], "top": None, "unread": []})

    def test_a_wildcard_or_placeholder_after_a_dot_is_not_cut_into_a_path(self):
        self.assertEqual(cited(it("x", "every test/route.test*.js and public/views/board.v<N>.js and docs/a.{md,txt}")), [])

    def test_the_guard_line_says_what_was_read(self):
        self.assertEqual(check_evidence({"T-1": it("Fix src/gone.js")}, tmp(self)),
                         ["T-1: cites src/gone.js, which is not on disk or on any branch read; correct the note, or record supersededBy if the work has gone"])


def dump(case, items):
    d = tmp(case)
    for name, docs in (("items", items), ("plan", {"r-a": {"name": "V1.0"}})):
        os.makedirs(os.path.join(d, name))
        for k, v in docs.items():
            json.dump(v, open(os.path.join(d, name, k + ".json"), "w"))
    return d


def pack_copy(dest):
    shutil.copytree(PACK, dest, ignore=shutil.ignore_patterns("__pycache__"))
    return os.path.join(dest, "scripts", "brain.py")


class CheckWiring(unittest.TestCase):
    """The hourly guard calls `brain.py check`, so a check that lives only in its own command is not wired."""
    def cli(self, d, *more, brain=BRAIN):
        r = subprocess.run([sys.executable, brain, "check", "--dump", d, *more], capture_output=True, text=True, env=GIT_ENV, timeout=120)
        return r.returncode, r.stdout

    def test_a_duplicate_pair_fails_the_check_and_shared_only_leaves_it_out(self):
        d = dump(self, {"T-1": it(SAME, release="r-a"), "T-2": it(SAME, release="r-a")})
        code, out = self.cli(d, "--repo", d)
        self.assertEqual(code, 1, out); self.assertIn("FAIL T-1 and T-2 read like the same job", out)
        code, out = self.cli(d, "--repo", d, "--shared-only")
        self.assertEqual(code, 0, out); self.assertNotIn("same job", out)

    def test_the_duplicate_threshold_reaches_the_command(self):
        d = dump(self, {"T-1": it(SAME, release="r-a"), "T-2": it(SAME, release="r-a")})
        cfg = os.path.join(d, "cfg.json"); json.dump({"guard": {"dupes_threshold": 1.01}}, open(cfg, "w"))
        code, out = self.cli(d, "--repo", d, "--config", cfg)
        self.assertEqual(code, 0, out); self.assertNotIn("same job", out)

    def test_an_open_superseded_task_fails_the_check(self):
        code, out = self.cli(dump(self, {"T-1": it(supersededBy="T-2"), "T-2": it("Another job", state="built")}), "--shared-only")
        self.assertEqual(code, 0, out)
        d = dump(self, {"T-1": it(supersededBy="T-2"), "T-2": it("Another job", state="built")})
        code, out = self.cli(d, "--repo", d)
        self.assertEqual(code, 1, out); self.assertIn("FAIL T-1: superseded by T-2 but still open", out)

    def test_with_repo_a_stale_citation_fails_and_a_present_file_passes(self):
        d = dump(self, {"T-1": it("Fix src/gone.js")})
        code, out = self.cli(d, "--repo", d)
        self.assertEqual(code, 1, out); self.assertIn("FAIL T-1: cites src/gone.js, which is in none of the folders given", out)
        write(d, "src/gone.js")
        code, out = self.cli(d, "--repo", d)
        self.assertEqual(code, 0, out); self.assertNotIn("cites", out)

    def test_evidence_can_be_switched_off_in_the_settings(self):
        d = dump(self, {"T-1": it("Fix src/gone.js")})
        cfg = os.path.join(d, "cfg.json"); json.dump({"guard": {"evidence": False}}, open(cfg, "w"))
        code, out = self.cli(d, "--repo", d, "--config", cfg)
        self.assertEqual(code, 0, out); self.assertNotIn("cites", out)

    def test_with_no_repository_and_no_repo_the_check_says_evidence_did_not_run(self):
        brain = pack_copy(os.path.join(tmp(self), "pack"))
        code, out = self.cli(dump(self, {"T-1": it("Fix src/gone.js")}), brain=brain)
        self.assertIn("WARN EVIDENCE not run", out); self.assertNotIn("cites", out)

    def test_the_hourly_path_reads_the_working_tree_and_every_fetched_branch(self):
        # The pack committed inside a repository and run with no --repo, exactly as .claude/board/board_check.py runs it.
        repo = git_repo(self)
        brain = pack_copy(os.path.join(repo, ".claude", "skills", "backlog-brain"))
        git(repo, "add", "-A"); git(repo, "commit", "-qm", "the pack")
        write(repo, "docs/draft.md")
        cites = {"T-1": it("Fix src/side.js"), "T-2": it("Fix src/feat.js"), "T-3": it("See docs/draft.md"), "T-4": it("Fix src/gone.js"),
                 "T-5": it("Fix src/old.js")}
        code, out = self.cli(dump(self, cites), brain=brain)
        self.assertEqual(code, 1, out)
        self.assertEqual(sorted(l.split(":")[0] for l in out.splitlines() if " cites " in l), ["FAIL T-4", "FAIL T-5"])
        self.assertIn("FAIL T-4: cites src/gone.js, which is not on disk, in HEAD or on any of the 3 branch(es) read", out)
        self.assertIn("WARN EVIDENCE could not read refs/remotes/origin/claude/stray", out)

    def test_the_branch_patterns_come_from_the_settings(self):
        repo = git_repo(self)
        brain = pack_copy(os.path.join(repo, ".claude", "skills", "backlog-brain"))
        git(repo, "add", "-A"); git(repo, "commit", "-qm", "the pack")
        d = dump(self, {"T-1": it("Fix src/feat.js")})
        cfg = os.path.join(d, "cfg.json"); json.dump({"guard": {"evidence_refs": ["refs/remotes/origin/claude/"]}}, open(cfg, "w"))
        code, out = self.cli(d, "--config", cfg, brain=brain)
        self.assertEqual(code, 1, out); self.assertIn("FAIL T-1: cites src/feat.js", out)

    def test_with_only_head_readable_a_missing_path_warns_and_does_not_fail(self):
        repo = tmp(self)
        git(repo, "init", "-q", "-b", "base")
        brain = pack_copy(os.path.join(repo, ".claude", "skills", "backlog-brain"))
        git(repo, "add", "-A"); git(repo, "commit", "-qm", "the pack")
        code, out = self.cli(dump(self, {"T-1": it("Fix src/gone.js")}), brain=brain)
        self.assertEqual(code, 0, out)
        self.assertIn("WARN T-1: cites src/gone.js", out); self.assertIn("(only HEAD was read: fetch the branches and run again)", out)


if __name__ == "__main__":
    unittest.main()
