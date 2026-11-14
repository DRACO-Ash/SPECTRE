"""Drag-and-drop install and upgrade (VH-366-G): read the project, write its settings record, copy the pack in, check it.

Detects the language, the gates the project already runs and whether it looks like a container to a store, from files
that are there, and never from a guess: a gate's minutes are left at 0 with a note, because the pack does not know how
long this project's gates take until it has measured them. Upgrading replaces the pack's code and keeps the project's own
settings and data, which live outside the pack folder (`.board/`). A failed self-check after a copy puts the previous
version back. Standard library only.
"""
import json
import os
import shutil
import subprocess
import sys

LANGS = (("package.json", "node"), ("pyproject.toml", "python"), ("requirements.txt", "python"), ("go.mod", "go"),
         ("Cargo.toml", "rust"), ("pom.xml", "java"), ("build.gradle", "java"), ("Gemfile", "ruby"))
SRC_DIRS = ("src", "lib", "app", "public", "server", "cmd", "pkg")
TEST_DIRS = ("test", "tests", "spec", "__tests__")
LINT_FILES = (".eslintrc", ".eslintrc.json", ".eslintrc.js", "eslint.config.js", "eslint.config.mjs", "ruff.toml", ".flake8", ".golangci.yml", "clippy.toml")
COPY_SKIP = shutil.ignore_patterns("__pycache__", "*.pyc", ".state-*", ".bundle-*")
DEST = os.path.join(".claude", "skills", "backlog-brain")
CONFIG = os.path.join(".board", "config.json")


def detect(project):
    """What is in the project, from files that exist. Returns {languages, src_dirs, gates, container}."""
    has = lambda n: os.path.exists(os.path.join(project, n))
    langs = sorted({lang for f, lang in LANGS if has(f)})
    src = [d for d in SRC_DIRS if os.path.isdir(os.path.join(project, d))]
    trig = [d + "/*" for d in src] or ["*"]
    note = "minutes not measured yet, TBC, re-verify: set it from this project's own runs"
    gates = []
    if any(os.path.isdir(os.path.join(project, d)) for d in TEST_DIRS):
        gates.append({"key": "tests", "label": "test suite", "minutes": 0, "triggers": trig, "note": note})
    if any(has(f) for f in LINT_FILES):
        gates.append({"key": "lint", "label": "lint", "minutes": 0, "triggers": trig, "note": note})
    container = has("Dockerfile") or has(".gitlab-ci.yml")
    if has("Dockerfile"):
        gates.append({"key": "container", "label": "container build", "minutes": 0, "triggers": ["Dockerfile"] + trig, "note": note})
    return {"languages": langs, "src_dirs": src, "gates": gates, "container": container}


def make_config(found, name, prefix):
    return {"schema": 1, "project": {"name": name, "ref_prefix": prefix},
            "releases": {"naming": "V{major}.{minor}", "start": "V1.0", "floor_min": 720, "cap_min": 840, "overhead_min": 0,
                         "pace": 1.0, "gate_savings": True, "fill_to_floor": True},
            "gates": found["gates"], "people": [], "agents": {"max_concurrent": 1},
            "working": {"hours_per_day": 8, "days_per_week": 5}, "risk_paths": []}


def steps(project, found, dest, config_path, wrote):
    s = [f"Settings record: {config_path}" + ("" if wrote else " (not written: this was a dry run)"),
         "Fill in the people (hours a week) and the agents that can run at once, then set each gate's minutes from this project's own runs.",
         f"Plan:      python3 {dest}/scripts/brain.py plan --config {config_path} --items items.json",
         f"Check:     python3 {dest}/scripts/brain.py check --dump <folder of your board's collections> --config {config_path}",
         f"Backup:    python3 {dest}/scripts/brain.py export --dump <folder> --out board.json",
         f"Relay:     python3 {dest}/scripts/brain.py relay --threads <dump>/threads --links <dump>/links --from <thread> --relation \"feeds work to\" --message \"...\"",
         "Schedule:  run the check hourly from whatever scheduler this project has (cron, a CI schedule, or a Claude Code Routine) and act on exit 1 or 3.",
         f"Board page: {dest}/assets/board/board.html. Publishing it changes external state, so an agent does it, in this order:",
         f"  1. publish the page as an artifact with the capabilities in {dest}/assets/board/capabilities.json and no URL;",
         f"  2. write the new board's link into {config_path} as board.url (and board.store, board.organisation if wanted);",
         f"  3. python3 {dest}/scripts/brain.py board seed --config {config_path}, and apply the batch it prints with ArtifactData:",
         "     the store refuses an update to a missing document, so the page cannot write until the seed has run;",
         "  4. have the session that coordinates the work watch the board, or answers and approvals reach nobody;",
         f"  5. set up the hourly sync from {dest}/assets/board/SYNC-TEMPLATE.md.",
         "  A later republish passes the board's URL and leaves the capabilities out. An upgrade reaches the page only when it is republished."]
    if found["container"]:
        s.append("This project has a Dockerfile or a GitLab pipeline: if it ships to a store, set releases.overhead_min to the measured minutes of your release steps.")
    return s


def install(src_root, project, name=None, prefix="PRJ-", write=False, upgrade=False):
    """Returns (report lines, ok). Without write nothing on disk changes."""
    from brain.model import load_config, ConfigError
    project = os.path.abspath(project)
    if not os.path.isdir(project):
        return [f"{project} is not a folder"], False
    dest = os.path.join(project, DEST)
    cfg_path = os.path.join(project, CONFIG)
    found = detect(project)
    cfg = make_config(found, name or os.path.basename(project) or "project", prefix)
    try:
        load_config(cfg)
    except ConfigError as e:
        return ["the settings record would be refused:"] + ["  " + p for p in e.problems], False
    out = [f"Detected: languages {', '.join(found['languages']) or 'none'}; source folders {', '.join(found['src_dirs']) or 'none'}; "
           f"gates {', '.join(g['key'] for g in found['gates']) or 'none'}; container {'yes' if found['container'] else 'no'}"]
    if os.path.exists(dest) and not upgrade:
        return out + [f"{dest} already exists. Use --upgrade to replace the pack's code and keep your settings and data."], False
    if upgrade and not os.path.exists(dest):
        return out + [f"nothing to upgrade at {dest}; install first."], False
    if not write:
        return out + ["dry run: nothing written (add --write)"] + steps(project, found, DEST, CONFIG, False), True
    tmp = dest + ".incoming"
    if os.path.exists(tmp):
        shutil.rmtree(tmp)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copytree(src_root, tmp, ignore=COPY_SKIP)
    prev = dest + ".previous"
    if os.path.exists(dest):
        if os.path.exists(prev):
            shutil.rmtree(prev)
        os.rename(dest, prev)
    os.rename(tmp, dest)
    wrote_cfg = False
    if not os.path.exists(cfg_path):
        os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
        json.dump(cfg, open(cfg_path, "w"), indent=1)
        wrote_cfg = True
    r = subprocess.run([sys.executable, os.path.join(dest, "scripts", "brain.py"), "selfcheck"], capture_output=True, text=True)
    out += [("settings kept: " if not wrote_cfg else "settings written: ") + cfg_path] + ["  " + l for l in r.stdout.splitlines()]
    if r.returncode != 0:
        shutil.rmtree(dest)
        if os.path.exists(prev):
            os.rename(prev, dest)
            out.append("the self-check failed, so the previous version was put back")
        else:
            out.append("the self-check failed, so the copy was removed")
        return out, False
    if os.path.exists(prev):
        shutil.rmtree(prev)
    if not wrote_cfg:
        # The kept record plans as before; a board is built only from a record the page can draw, so say now what would stop it.
        from brain.board import page_problems
        try:
            kept = load_config(json.load(open(cfg_path)))
            out += [f"before seeding a board from {CONFIG}: {p}" for p in page_problems(kept)]
        except (ConfigError, ValueError, OSError) as e:
            out.append(f"the kept settings record does not load: {e}")
    return out + steps(project, found, DEST, CONFIG, True), True
