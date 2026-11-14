#!/usr/bin/env python3
"""Backlog Brain command line. Standard library only.

  brain.py plan --config .board/config.json --items items.json [--rows rows.json] [--json]
  brain.py events --log events.jsonl --state state.json [--now 2026-10-06T20:00:00Z] [--write]
  brain.py relay --threads DIR --links DIR --from t-backlog --relation "feeds work to" --message "..."
  brain.py relay --threads DIR --from t-backlog --to t-dev1 [--kind poke]
  brain.py approval --question "..." --option "Label|detail|rec" [--context ...] [--image ID:alt:caption ...]
  brain.py idle --dump DIR --sha SHA --meta FILE [--threshold 3] [--store]
  brain.py check --dump DIR [--config config.json] [--now ISO] [--fallback FILE] [--repo DIR ...] [--shared-only]
  brain.py export --dump DIR --out board.json [--now ISO]
  brain.py import --file board.json --out EMPTY_DIR
  brain.py install --project DIR [--name N] [--prefix PRJ-] [--write] [--upgrade]
  brain.py dupes --items DIR_or_FILE [--threshold 0.55] [--top 20]
  brain.py evidence --items DIR_or_FILE --repo DIR [--repo DIR ...]
  brain.py selfcheck
  brain.py guide [--for pack|board] [--config config.json]
  brain.py board settings --config config.json
  brain.py board seed --config config.json [--now ISO]
  brain.py selftest
"""
import argparse, json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from brain.api import run  # noqa: E402
from brain.model import ConfigError  # noqa: E402


def hm(m):
    m = round(m)
    return f"{m // 60}h{m % 60:02d}"


def events_cmd(a):
    """Replays an event log into a state file. Prints what happened; exits 1 when any line was skipped, stale or refused."""
    import datetime
    from brain.events import replay, save_state, parse_time
    now = a.now or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if parse_time(now) is None:
        print("--now must be an ISO 8601 UTC time ending in Z")
        return 2
    state = json.load(open(a.state)) if os.path.exists(a.state) else None
    new, rep = replay(state, open(a.log).read(), now)
    print(f"applied {rep['applied']}, duplicate {rep['duplicate']}, stale {rep['stale']}, refused {rep['refused']}, bad lines {len([p for p in rep['problems'] if 'not JSON' in p])}")
    for p in rep["problems"]:
        print("  " + p)
    if a.write:
        save_state(a.state, new)
        print("state written to", a.state)
    else:
        print("dry run: nothing written (add --write)")
    return 1 if rep["problems"] else 0


def _load_items(path):
    """Items as {ref: doc} from a folder of JSON documents (a board dump) or a JSON file holding a list or an object."""
    if os.path.isdir(path):
        out = {}
        for f in sorted(os.listdir(path)):
            if f.endswith(".json"):
                x = json.load(open(os.path.join(path, f)))
                out[f[:-5]] = x.get("data", x) if isinstance(x, dict) else x
        return out
    x = json.load(open(path))
    return {str(i.get("ref", n)): i for n, i in enumerate(x)} if isinstance(x, list) else x


def dupes_cmd(a):
    """Candidate duplicates for a person to look at. Exit 1 when there are any, 2 on unusable input. Nothing is changed."""
    from brain.dupes import find
    try:
        items = _load_items(a.items)
    except (OSError, ValueError) as e:
        print("cannot read the items:", e)
        return 2
    pairs = find(items, a.threshold, a.top)
    for score, x, y in pairs:
        print(f"{score:.2f}  {x}  {y}   {(items[x].get('task') or '')[:60]}  |  {(items[y].get('task') or '')[:60]}")
    print(f"{len(pairs)} candidate pair(s) at {a.threshold} or above; none is merged or removed")
    return 1 if pairs else 0


def evidence_cmd(a):
    """Open tasks that cite a file none of the given trees has. Exit 1 when there are any, 2 on unusable input."""
    from brain.evidence import missing
    for r in a.repo:
        if not os.path.isdir(r):
            print(f"{r} is not a folder")
            return 2
    try:
        items = _load_items(a.items)
    except (OSError, ValueError) as e:
        print("cannot read the items:", e)
        return 2
    rows = missing(items, a.repo)
    for ref, p in rows:
        print(f"{ref}: cites {p}, which is in none of the trees given")
    print(f"{len(rows)} open task(s) cite a missing path; none is edited")
    return 1 if rows else 0


def _now(text):
    import datetime
    from brain.events import parse_time
    if text is None:
        return datetime.datetime.now(datetime.timezone.utc)
    t = parse_time(text)
    if t is None:
        raise ValueError("--now must be an ISO 8601 UTC time ending in Z")
    return t


def check_cmd(a):
    """The freshness guard. Exit 0 clean, 1 a fault, 2 unusable input, 3 read from an export because the store was unavailable."""
    import time
    from brain.guard import check
    from brain.bundle import read_dump, import_board
    try:
        now = _now(a.now)
        cfg = json.load(open(a.config)) if a.config else {}
        degraded, age = None, None
        try:
            col = read_dump(a.dump)
            if "items" not in col or "plan" not in col:
                raise OSError("the dump has no items or no plan")
            age = (time.time() - os.path.getmtime(os.path.join(a.dump, "items"))) / 60
        except OSError:
            if not a.fallback:
                raise
            col, problems = import_board(json.load(open(a.fallback)))
            if problems:
                print("the fallback export is refused:", *problems, sep="\n  ")
                return 2
            stamp = json.load(open(a.fallback)).get("exported_at")
            from brain.events import parse_time
            age = (now - parse_time(stamp)).total_seconds() / 60 if parse_time(stamp) else 10 ** 9
            degraded = stamp
    except (ValueError, OSError) as e:
        print("cannot read the board:", e)
        return 2
    meta = (col.get("board") or {}).get("meta")      # the header read from the dump itself (VH-584); --meta still wins
    meta = meta if isinstance(meta, dict) else None
    if a.meta:
        m = json.load(open(a.meta))
        meta = m.get("data", m)
    from brain import guard
    fails, warns, rows = check(col["items"], col["plan"], cfg, age, meta, now)
    # Intake, thread structure and the forecast read the other collections of the same dump, and only when it holds them.
    if "intake" in col:
        fails += guard.check_intake(col["intake"], col["items"], now, cfg)
    if "threads" in col and "links" in col:
        fails += guard.check_threads(col["threads"], col["links"], cfg)
    # Keeping the backlog accurate (VH-377): overtaken tasks, duplicates and stale citations, every run. --shared-only leaves them
    # out so .claude/board/parity_check.py compares, like with like, only the checks the legacy guard also has.
    if not a.shared_only:
        fails += guard.check_superseded(col["items"])
        fails += guard.check_duplicates(col["items"], cfg)
        g = cfg.get("guard") or {}
        if g.get("evidence", True) is not False:
            from brain.evidence import git_trees
            if a.repo:
                fails += guard.check_evidence(col["items"], a.repo, [], "is in none of the folders given")
            else:
                got = git_trees(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."), g.get("evidence_refs") or ["refs/remotes/origin/"])
                n = len(got["trees"])
                found = guard.check_evidence(col["items"], [got["top"]] if got["top"] else [], [t for _, t in got["trees"]],
                                             f"is not on disk, in HEAD or on any of the {n - 1} branch(es) read")
                if not n:
                    warns.append("EVIDENCE not run: the pack is not inside a git repository with a commit, and no --repo was given")
                elif n == 1:
                    # HEAD alone: an unfetched branch could hold any of these, so the reader is told rather than told to rewrite work.
                    warns += [f + " (only HEAD was read: fetch the branches and run again)" for f in found]
                else:
                    fails += found
                warns += [f"EVIDENCE could not read {r}, so its files were not counted" for r in got["unread"]]
    tooling = {v.get("name") for v in col["plan"].values() if v.get("kind") == "tooling"}
    # VH-468: a release holding nothing but research, investigation or document work uploads nothing to the store either.
    tooling |= guard.document_only(col["items"], col["plan"])
    warns += guard.overhead_warnings(rows, tooling, cfg)
    if degraded:
        print(f"DEGRADED: the store was unavailable, so this reads the export made at {degraded}; treat every figure as that old")
    if a.table or a.state_block:
        print(guard.table(rows, tooling, cfg))
        if "accuracy" in col:
            for line in guard.lane_lines(rows, guard.lane_paces(col["accuracy"]), tooling, cfg):
                print(line)
    else:
        for k, (n, m) in sorted(rows.items()):
            print(f"{k}: {n} open, {m} priced minutes")
    for w in warns:
        print("WARN", w)
    for f in fails:
        print("FAIL", f)
    if a.state_block and not any(f.startswith("STALE DUMP") for f in fails):
        guard.write_block(a.state_block, rows, now.strftime("%Y-%m-%d %H:%M UTC"), a.extra, tooling, cfg)
        print("state block written to", a.state_block)
    return 1 if fails else (3 if degraded else 0)


def export_cmd(a):
    from brain.bundle import read_dump, export_board, save
    try:
        now = a.now or _now(None).strftime("%Y-%m-%dT%H:%M:%SZ")
        _now(now)
        col = read_dump(a.dump)
        if not col:
            print("the dump holds no collections")
            return 2
        save(a.out, export_board(col, now))
    except (ValueError, OSError) as e:
        print("export failed:", e)
        return 2
    print(f"exported {', '.join(f'{k} {len(v)}' for k, v in sorted(col.items()))} to {a.out}")
    return 0


def import_cmd(a):
    from brain.bundle import import_board, write_dump
    try:
        col, problems = import_board(json.load(open(a.file)))
        if problems:
            print("the file is refused:", *problems, sep="\n  ")
            return 2
        os.makedirs(a.out, exist_ok=True)
        write_dump(a.out, col)
    except (ValueError, OSError) as e:
        print("import failed:", e)
        return 2
    print(f"imported {', '.join(f'{k} {len(v)}' for k, v in sorted(col.items()))} into {a.out}")
    return 0


def selfcheck_cmd():
    """Run on install and on upgrade: the settings example loads, the tests pass, and a board survives export and import."""
    import io, tempfile, unittest
    from brain.model import load_config
    from brain.bundle import export_board, import_board
    here = os.path.dirname(os.path.abspath(__file__))
    ok = True
    try:
        load_config(json.load(open(os.path.join(here, "..", "assets", "example", "config.json"))))
        print("ok   the example settings record loads")
    except (ConfigError, OSError, ValueError) as e:
        print("FAIL the example settings record:", e); ok = False
    items = json.load(open(os.path.join(here, "..", "assets", "example", "items.json")))
    docs = {str(i.get("ref", n)): i for n, i in enumerate(items if isinstance(items, list) else items.get("items", []))}
    back, problems = import_board(export_board({"items": docs}, "2026-10-06T00:00:00Z"))
    if problems or back.get("items") != docs:
        print("FAIL the export and import round trip:", problems); ok = False
    else:
        print(f"ok   a board of {len(docs)} items survives export and import unchanged")
    if os.environ.get("BRAIN_SELFCHECK_RUNNING"):
        print("skip the pack's own tests: already inside a self-check")
        return 0 if ok else 1
    os.environ["BRAIN_SELFCHECK_RUNNING"] = "1"
    try:
        suite = unittest.defaultTestLoader.discover(os.path.join(here, "..", "tests"))
        res = unittest.TextTestRunner(stream=io.StringIO()).run(suite)     # in memory: no file handle left open
    finally:
        del os.environ["BRAIN_SELFCHECK_RUNNING"]
    print(f"{'ok  ' if res.wasSuccessful() else 'FAIL'} the pack's own tests: {res.testsRun} run, {len(res.failures) + len(res.errors)} failed, "
          f"{len(res.skipped)} skipped")
    # A skipped check proves nothing, so each reason is named once: a page that shipped with every browser check skipped must
    # not print the same line as one that ran them (VH-584).
    for why in sorted({str(r) for _, r in res.skipped}):
        print(f"skip {sum(1 for _, r in res.skipped if str(r) == why)}: {why}")
    return 0 if ok and res.wasSuccessful() else 1


def _load_dir(d):
    out = {}
    for f in sorted(os.listdir(d)):
        if f.endswith(".json"):
            x = json.load(open(os.path.join(d, f)))
            out[f[:-5]] = x.get("data", x)
    return out


def board_cmd(a):
    """The board page's settings document, or the whole batch a new board needs, as JSON for ArtifactData (VH-584). It prints
    and writes nothing: the command line cannot write to an Artifact store, so an agent applies the batch. Exit 2 on a record
    the pack refuses, with every problem listed."""
    from brain.board import seed, settings_doc
    from brain.model import load_config
    try:
        cfg = load_config(json.load(open(a.config)))
        now = a.now or _now(None).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        _now(now.replace(".000Z", "Z"))
        out = settings_doc(cfg) if a.what == "settings" else seed(cfg, now)
    except ConfigError as e:
        print("The settings record is refused:", *e.problems, sep="\n  ", file=sys.stderr)
        return 2
    except (ValueError, OSError) as e:
        print("cannot build it:", e, file=sys.stderr)
        return 2
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


def relay_cmd(a):
    """Prints the poke requests for every target of a relationship, as JSON. Exit 2 when nothing can be sent without the owner.
    With --to it checks one poke against the standing approval instead and prints the target session id (relay_check.py, VH-584)."""
    from brain.relay import check, poke_requests
    if a.dst:
        try:
            print(check(_load_dir(a.threads), a.src, a.dst, a.kind))
        except (ValueError, OSError) as e:
            print("needs the owner:", e, file=sys.stderr)
            return 2
        return 0
    if not (a.links and a.relation and a.message):
        print("needs the owner: give --to to check one poke, or --links, --relation and --message to build them", file=sys.stderr)
        return 2
    try:
        reqs, owner = poke_requests(_load_dir(a.threads), _load_dir(a.links), a.src, a.relation, a.message)
    except (ValueError, OSError) as e:
        print("needs the owner:", e, file=sys.stderr)
        return 2
    print(json.dumps({"requests": reqs, "needs_owner": owner}, indent=1))
    return 2 if owner and not reqs else 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] == ["approval"]:      # the helpers that moved into the pack keep their own arguments (VH-584)
        from brain.approvals import main as approval_main
        return approval_main(argv[1:])
    if argv[:1] == ["idle"]:
        from brain.idle import main as idle_main
        return idle_main(argv[1:])
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--config", required=True); p.add_argument("--items", required=True)
    p.add_argument("--rows"); p.add_argument("--json", action="store_true")
    g = sub.add_parser("guide")
    g.add_argument("--for", dest="audience", choices=("pack", "board"), default="pack")
    g.add_argument("--config", help="fill the board guide from this settings record instead of the page's own defaults")
    sub.add_parser("approval", help="build the board write that raises an approval (brain/approvals.py; its own arguments)")
    sub.add_parser("idle", help="the hourly sync's idle check (brain/idle.py; its own arguments)")
    bd = sub.add_parser("board")
    bd.add_argument("what", choices=("settings", "seed")); bd.add_argument("--config", required=True); bd.add_argument("--now")
    e = sub.add_parser("events")
    e.add_argument("--log", required=True); e.add_argument("--state", required=True)
    e.add_argument("--now"); e.add_argument("--write", action="store_true")
    r = sub.add_parser("relay")
    r.add_argument("--threads", required=True); r.add_argument("--links")
    r.add_argument("--from", dest="src", required=True); r.add_argument("--relation"); r.add_argument("--message")
    r.add_argument("--to", dest="dst"); r.add_argument("--kind", default="poke")
    c = sub.add_parser("check")
    c.add_argument("--dump", required=True); c.add_argument("--config"); c.add_argument("--now"); c.add_argument("--fallback")
    c.add_argument("--meta"); c.add_argument("--state-block"); c.add_argument("--extra", default=""); c.add_argument("--table", action="store_true")
    c.add_argument("--repo", action="append", help="a folder whose files count as present; when absent, HEAD and every fetched branch are read")
    c.add_argument("--shared-only", action="store_true", help="only the checks the legacy guard also has, for parity_check.py")
    x = sub.add_parser("export")
    x.add_argument("--dump", required=True); x.add_argument("--out", required=True); x.add_argument("--now")
    i = sub.add_parser("import")
    i.add_argument("--file", required=True); i.add_argument("--out", required=True)
    n = sub.add_parser("install")
    n.add_argument("--project", required=True); n.add_argument("--name"); n.add_argument("--prefix", default="PRJ-")
    n.add_argument("--write", action="store_true"); n.add_argument("--upgrade", action="store_true")
    d = sub.add_parser("dupes")
    d.add_argument("--items", required=True); d.add_argument("--threshold", type=float, default=0.55); d.add_argument("--top", type=int, default=20)
    v = sub.add_parser("evidence")
    v.add_argument("--items", required=True); v.add_argument("--repo", required=True, action="append")
    sub.add_parser("selfcheck")
    sub.add_parser("selftest")
    a = ap.parse_args(argv)
    if a.cmd == "guide":
        from brain.guide import render_text, load_guide
        settings = None
        if a.config:
            from brain.board import settings_doc
            from brain.model import load_config
            try:
                settings = settings_doc(load_config(json.load(open(a.config))))
            except ConfigError as e:
                print("The settings record is refused:", *e.problems, sep="\n  ", file=sys.stderr)
                return 2
            except (ValueError, OSError) as e:
                print("cannot read the settings record:", e, file=sys.stderr)
                return 2
        print(render_text(load_guide(), a.audience, settings))
        return 0
    if a.cmd == "board":
        return board_cmd(a)
    if a.cmd == "dupes":
        return dupes_cmd(a)
    if a.cmd == "evidence":
        return evidence_cmd(a)
    if a.cmd == "check":
        return check_cmd(a)
    if a.cmd == "export":
        return export_cmd(a)
    if a.cmd == "import":
        return import_cmd(a)
    if a.cmd == "install":
        from brain.install import install
        lines, ok = install(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."), a.project, a.name, a.prefix, a.write, a.upgrade)
        print(*lines, sep="\n")
        return 0 if ok else 1
    if a.cmd == "selfcheck":
        return selfcheck_cmd()
    if a.cmd == "relay":
        return relay_cmd(a)
    if a.cmd == "events":
        return events_cmd(a)
    if a.cmd == "selftest":
        import unittest
        suite = unittest.defaultTestLoader.discover(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tests"))
        return 0 if unittest.TextTestRunner(verbosity=1).run(suite).wasSuccessful() else 1
    try:
        res = run(json.load(open(a.config)), json.load(open(a.items)), json.load(open(a.rows)) if a.rows else None)
    except ConfigError as e:
        print("The settings record is refused:", *e.problems, sep="\n  ")
        return 2
    if a.json:
        print(json.dumps(res, indent=1))
        return 0
    print(f"pace {res['pace_used']:.2f} from {res['pace_source']}")
    for rel, f in zip(res["releases"], res["forecasts"]):
        print(f"\n{rel['name']}: {len(rel['items'])} items, {rel['priced']} priced min, gates {', '.join(rel['gates']) or 'none'}")
        print(f"  forecast {hm(f['low_min'])} to {hm(f['high_min'])} (middle {hm(f['mid_min'])}), people's time {f['human_min']} min, evidence: {'; '.join(f['pace_sources'])}")
        for it in rel["items"]:
            print(f"    {it['ref']:<12}{it['minutes']:>5}m  {it['reason']}")
        for i, lane in enumerate(rel["lanes"], 1):
            print(f"  lane {i} ({lane['minutes']}m): {', '.join(lane['refs'])}")
    t = res["tooling"]
    if t["items"]:   # VH-467: the tooling plan was only visible with --json
        print(f"\ntooling: {len(t['items'])} items, {t['priced']} priced min, {hm(t['build_min'])} of build; {t['note']}")
        for it in t["items"]:
            print(f"    {it['ref']:<12}{it['minutes']:>5}m")
    for k in ("waiting", "off_path"):
        for x in res[k]:
            print(f"\n{k.replace('_', ' ')}: {x['ref']} - {x['why']}")
    for w in res["warnings"]:
        print("WARNING", w)
    return 0


if __name__ == "__main__":
    sys.exit(main())
