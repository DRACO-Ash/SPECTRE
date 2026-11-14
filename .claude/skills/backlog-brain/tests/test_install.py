import json, os, shutil, subprocess, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from brain.install import detect, install, DEST, CONFIG
from brain.model import load_config

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
BRAIN = os.path.join(ROOT, "scripts", "brain.py")


def project(**files):
    d = tempfile.mkdtemp()
    for f in files.get("dirs", ()):
        os.makedirs(os.path.join(d, f))
    for f in files.get("files", ()):
        open(os.path.join(d, f), "w").write("{}")
    return d


def full():
    return project(dirs=("src", "test"), files=("package.json", "Dockerfile", ".eslintrc.json"))


class Env(unittest.TestCase):
    def setUp(self):
        self._old = os.environ.get("BRAIN_SELFCHECK_RUNNING")
        os.environ["BRAIN_SELFCHECK_RUNNING"] = "1"      # a nested self-check would run this suite again
        self._old_bc = os.environ.get("PYTHONDONTWRITEBYTECODE")
        os.environ["PYTHONDONTWRITEBYTECODE"] = "1"      # so the installed copy's own self-check leaves no cache to confuse a test

    def tearDown(self):
        for key, old in (("BRAIN_SELFCHECK_RUNNING", self._old), ("PYTHONDONTWRITEBYTECODE", self._old_bc)):
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old


class Detect(Env):
    def test_what_is_there_is_found_and_what_is_not_is_not_invented(self):
        f = detect(full())
        self.assertEqual((f["languages"], f["src_dirs"], f["container"]), (["node"], ["src"], True))
        self.assertEqual([g["key"] for g in f["gates"]], ["tests", "lint", "container"])     # never "build", the page's own node
        self.assertTrue(all(g["minutes"] == 0 and "TBC" in g["note"] for g in f["gates"]))      # minutes are never guessed
        e = detect(project())
        self.assertEqual((e["languages"], e["gates"], e["container"], e["src_dirs"]), ([], [], False, []))

    def test_each_language_marker_is_read(self):
        for marker, lang in (("pyproject.toml", "python"), ("go.mod", "go"), ("Cargo.toml", "rust"), ("pom.xml", "java")):
            self.assertEqual(detect(project(files=(marker,)))["languages"], [lang], marker)


class Install(Env):
    def test_a_dry_run_changes_nothing(self):
        p = full()
        lines, ok = install(ROOT, p, "Demo", "DM-")
        self.assertTrue(ok); self.assertIn("dry run", " ".join(lines))
        self.assertFalse(os.path.exists(os.path.join(p, DEST)) or os.path.exists(os.path.join(p, CONFIG)))

    def test_an_install_copies_the_pack_writes_a_valid_record_and_the_installed_copy_plans(self):
        p = full()
        src = os.path.join(tempfile.mkdtemp(), "pack")
        shutil.copytree(ROOT, src, ignore=shutil.ignore_patterns("__pycache__"))
        os.makedirs(os.path.join(src, "brain", "__pycache__")); open(os.path.join(src, "brain", "__pycache__", "junk.pyc"), "w").write("x")
        lines, ok = install(src, p, "Demo", "DM-", write=True)
        self.assertTrue(ok, lines)
        self.assertFalse(any("__pycache__" in dp for dp, _, _ in os.walk(os.path.join(p, DEST))))      # compiled caches are not copied
        cfg = json.load(open(os.path.join(p, CONFIG)))
        load_config(cfg)                                           # the written record passes the pack's own validation
        self.assertEqual(cfg["project"], {"name": "Demo", "ref_prefix": "DM-"})
        items = os.path.join(p, "items.json")
        json.dump([{"ref": "DM-1", "minutes": 30, "priority": "high", "files": ["src/a.js"]}], open(items, "w"))
        r = subprocess.run([sys.executable, os.path.join(p, DEST, "scripts", "brain.py"), "plan", "--config", os.path.join(p, CONFIG), "--items", items], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr); self.assertIn("DM-1", r.stdout)
        self.assertTrue(os.path.exists(os.path.join(p, DEST, "assets", "board", "board.html")))   # the page arrives with the pack (VH-584)
        self.assertIn("board seed --config", " ".join(lines))                                     # and the publish steps are printed
        b = subprocess.run([sys.executable, os.path.join(p, DEST, "scripts", "brain.py"), "board", "seed", "--config", os.path.join(p, CONFIG)], capture_output=True, text=True)
        self.assertEqual(b.returncode, 0, b.stderr)                                               # the installer's own record seeds a board

    def test_a_second_install_is_refused_and_changes_nothing(self):
        p = full()
        install(ROOT, p, "Demo", "DM-", write=True)
        marker = os.path.join(p, DEST, "marker.txt"); open(marker, "w").write("x")
        lines, ok = install(ROOT, p, "Demo", "DM-", write=True)
        self.assertFalse(ok); self.assertIn("--upgrade", " ".join(lines)); self.assertTrue(os.path.exists(marker))

    def test_an_upgrade_replaces_the_code_and_keeps_the_settings(self):
        p = full()
        install(ROOT, p, "Demo", "DM-", write=True)
        cfg_path = os.path.join(p, CONFIG)
        cfg = json.load(open(cfg_path)); cfg["people"] = [{"id": "ann", "hours_per_week": 12}]; json.dump(cfg, open(cfg_path, "w"))
        marker = os.path.join(p, DEST, "brain", "stale.py"); open(marker, "w").write("x")
        lines, ok = install(ROOT, p, write=True, upgrade=True)
        self.assertTrue(ok, lines)
        self.assertFalse(os.path.exists(marker))                             # the old code is gone
        self.assertEqual(json.load(open(cfg_path))["people"], [{"id": "ann", "hours_per_week": 12}])   # the settings are not touched
        self.assertFalse(os.path.exists(os.path.join(p, DEST + ".previous")))
        self.assertFalse(any(l.startswith("before seeding a board") for l in lines), lines)
        cfg["gates"].append({"key": "build", "minutes": 0, "triggers": ["Dockerfile"]}); json.dump(cfg, open(cfg_path, "w"))   # as an older installer wrote it
        lines, ok = install(ROOT, p, write=True, upgrade=True)
        self.assertTrue(ok, lines)                                           # the record still plans, so the upgrade stands
        self.assertTrue(any(l.startswith("before seeding a board") and "rename it 'container'" in l for l in lines), lines)

    def test_an_existing_record_is_never_overwritten_by_a_first_install(self):
        p = full()
        os.makedirs(os.path.join(p, ".board")); open(os.path.join(p, CONFIG), "w").write('{"keep": true}')
        lines, ok = install(ROOT, p, "Demo", "DM-", write=True)
        self.assertEqual(json.load(open(os.path.join(p, CONFIG))), {"keep": True})
        self.assertIn("settings kept", " ".join(lines))

    def test_a_failed_self_check_puts_the_previous_version_back(self):
        p = full()
        install(ROOT, p, "Demo", "DM-", write=True)
        marker = os.path.join(p, DEST, "marker.txt"); open(marker, "w").write("keep me")
        bad_src = os.path.join(tempfile.mkdtemp(), "pack")
        shutil.copytree(ROOT, bad_src, ignore=shutil.ignore_patterns("__pycache__"))
        json.dump({"schema": 99}, open(os.path.join(bad_src, "assets", "example", "config.json"), "w"))
        lines, ok = install(bad_src, p, write=True, upgrade=True)
        self.assertFalse(ok); self.assertIn("previous version was put back", " ".join(lines))
        self.assertEqual(open(marker).read(), "keep me")
        self.assertFalse(os.path.exists(os.path.join(p, DEST + ".previous")))

    def test_a_failed_first_install_leaves_no_pack_behind(self):
        p = full()
        bad_src = os.path.join(tempfile.mkdtemp(), "pack")
        shutil.copytree(ROOT, bad_src, ignore=shutil.ignore_patterns("__pycache__"))
        json.dump({"schema": 99}, open(os.path.join(bad_src, "assets", "example", "config.json"), "w"))
        lines, ok = install(bad_src, p, "Demo", "DM-", write=True)
        self.assertFalse(ok); self.assertFalse(os.path.exists(os.path.join(p, DEST)))

    def test_nothing_to_upgrade_and_not_a_folder_are_refused(self):
        self.assertFalse(install(ROOT, project(), write=True, upgrade=True)[1])
        self.assertFalse(install(ROOT, os.path.join(tempfile.mkdtemp(), "nope"))[1])

    def test_a_record_the_pack_would_refuse_is_never_written(self):
        p = full()
        lines, ok = install(ROOT, p, "Demo", "not a prefix!", write=True)
        self.assertFalse(ok); self.assertFalse(os.path.exists(os.path.join(p, CONFIG)))


class Command(Env):
    def test_the_command_installs_and_exits_one_on_a_refusal(self):
        p = full()
        r = subprocess.run([sys.executable, BRAIN, "install", "--project", p, "--name", "Demo", "--prefix", "DM-", "--write"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = subprocess.run([sys.executable, BRAIN, "install", "--project", p, "--name", "Demo", "--write"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)


if __name__ == "__main__":
    unittest.main()
