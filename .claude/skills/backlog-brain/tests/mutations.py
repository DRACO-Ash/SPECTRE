"""Red before green for every rule: revert the thing a test pins and confirm the suite fails.

A mutation whose anchor matches zero or several places did not apply, and its green would prove nothing, so
each anchor is checked to be unique first. A red suite proves nothing either when the suite is red with no
mutation at all, so the unmutated copy is run first and must pass (VH-377 found it failing from VH-380 on, so
every mutation had read as caught). Run: python3 tests/mutations.py"""
import os, shutil, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
M = [
 ("an item with no files must trigger every gate", "brain/model.py", "    if not files:\n        return set(keys)", "    if not files:\n        return set()"),
 ("settings problems are reported together", "brain/model.py", 'r["floor_min"] > r["cap_min"]', "False"),
 ("a dependency is not placed before what it needs", "brain/optimiser.py", 'd in done or d in placed or d in this or d not in refs', "True"),
 ("a locked item stays put", "brain/optimiser.py", 'if i["lock"] == name:', "if False:"),
 ("the cap holds", "brain/optimiser.py", "<= (target if limit is None else limit)", "<= 10**9"),
 ("waiting items take no capacity", "brain/optimiser.py", " and i not in waiting and i not in tooling]", " and i not in tooling]"),
 ("tooling is planned apart", "brain/optimiser.py", " and i not in tooling]", "]"),
 ("a low-priority item does not pay for a new gate", "brain/optimiser.py", "if adds_gate and blocked is not None and key > blocked:", "if False:"),
 ("fewer gates forecast lower", "brain/optimiser.py", 'saved = sum(g.get("minutes", 0) for g in cfg["gates"] if g["key"] not in gates_used)', "saved = 0"),
 ("items sharing a file share a lane", "brain/optimiser.py", 'parent[find(i["ref"])] = find(owner[f])', "pass"),
 ("a cycle is reported", "brain/optimiser.py", 'cycles.append(" -> ".join(trail + [ref]))', "pass"),
 ("an oversize item is reported", "brain/optimiser.py", 'warnings.append(f"{i[\'ref\']}: needs', 'str(f"{i[\'ref\']}: needs'),
 ("a release under its floor is filled", "brain/optimiser.py", 'if cfg["releases"]["fill_to_floor"]:', "if False:"),
 ("thin evidence is not trusted", "brain/resources.py", 'if s and s["n"] >= MIN_ROWS:', "if s:"),
 ("the range is ordered", "brain/resources.py", 'return s["p25"], s["p50"], s["p75"], f"{label}', 'return s["p75"], s["p50"], s["p25"], f"{label}'),
 ("people are warned when they are the limit", "brain/resources.py", "human > 0.8 * avail", "human > 10**12"),
 ("a development thread gets one branch", "brain/threads.py", 'req["outcome_branch"] = thread.get("branch") or branch_for(thread)', "pass"),
 ("a branch comes from the name only", "brain/threads.py", 's = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")', 's = str(text)'),
 ("a thread with no lane starts nothing", "brain/threads.py", 'lines.append("- none assigned yet. Do not start any work.")', 'lines.append("- none assigned yet.")'),
 ("the brief says how to make the branch", "brain/threads.py", 'git checkout -b {br} origin/{base}', 'git branch'),
 ("a result with no session id is refused", "brain/threads.py", "if not SESSION_RE.fullmatch(sid):", "if False:"),
 ("a nameless thread is refused", "brain/threads.py", 'if not thread.get("name"):', "if False:"),
 ("clashing lanes are reported", "brain/threads.py", "if f in seen and seen[f] != name:", "if False:"),
 ("relationships reach the brief", "brain/threads.py", 'lines.append(f"- {thread[\'name\']} {kind} {who}" if direction == "out" else f"- {who} {kind} {thread[\'name\']}")', "pass"),
 ("human time with nobody configured is reported", "brain/resources.py", 'if not cfg["people"] and human:', "if False:"), ("other threads are told to wake Backlog", "brain/threads.py", 'if thread.get("role") != "backlog":', "if False:"),
 ("the wake line names Backlog's session", "brain/threads.py", 'who = f"Backlog ({bsid})" if bsid else', 'who = f"Backlog" if False else'),
 ("the page patch refuses a missing or repeated anchor", "brain/page_patch.py", "    if n != 1:", "    if False:"),
 ("the page patch refuses a second apply", "brain/page_patch.py", "    if BEGIN in html:", "    if False:"),
 ("a guide for nobody is refused", "brain/guide.py", "    if audience not in AUDIENCES:", "    if False:"),
 ("the same event twice changes nothing", "brain/events.py", 'if event["id"] in state["applied"]:', "if False:"),
 ("an event older than the last read is refused", "brain/events.py", 'if last is not None and parse_time(event["at"]) < last:', "if False:"),
 ("an event with a problem is refused whole", "brain/events.py", "    if problems:\n        return state, \"refused\"", "    if False:\n        return state, \"refused\""),
 ("a bad line is reported with its number", "brain/events.py", 'problems.append(f"line {n}: not JSON, skipped")', "pass"),
 ("a boolean is not a number", "brain/events.py", "not isinstance(v, bool) and v > 0", "v > 0"),
 ("a replay records when the log was read", "brain/events.py", 'state["last_read"] = now', "pass"),
 ("a failed write leaves the old file whole", "brain/events.py", 'fd, tmp = tempfile.mkstemp(dir=d, prefix=".state-", suffix=".tmp")', "fd, tmp = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC), path"),
 ("a dry run writes nothing", "scripts/brain.py", "    if a.write:\n        save_state", "    if True:\n        save_state"),
 ("a problem in the log makes the command exit one", "scripts/brain.py", 'return 1 if rep["problems"] else 0', "return 0"),
 ("a sender with no session is not covered", "brain/relay.py", 'if not session_of(threads[src]):', "if False:"),
 ("a thread does not poke itself", "brain/relay.py", "if src == dst:", "if False:"),
 ("only a poke is covered", "brain/relay.py", "if kind not in ALLOWED_KINDS:", "if False:"),
 ("a relationship names a target once", "brain/relay.py", 'and l["to"] not in seen:', "and True:"),
 ("a link to a ghost is ignored", "brain/relay.py", 'and l.get("to") in threads and', "and True and"),
 ("targets keep the board's order", "brain/relay.py", 'key=lambda k: (threads[k].get("order", 99), k)', "key=lambda k: k"),
 ("a relay is stamped with the clock", "brain/relay.py", "now = now or datetime.datetime.now(datetime.timezone.utc)", "now = now or datetime.datetime(2000, 1, 1, tzinfo=datetime.timezone.utc)"),
 ("an unsendable target goes to the owner", "brain/relay.py", 'owner.append({"to": dst, "why": str(e)})', "pass"),
 ("a relay with no message is refused", "brain/relay.py", "if not isinstance(message, str) or not message.strip():", "if False:"),
 ("nothing sendable exits two", "scripts/brain.py", "return 2 if owner and not reqs else 0", "return 0"),
 ('a document-only release is found', 'brain/guard.py', 'return {k for k, v in seen.items() if k != "Unassigned" and v and all(v)}', 'return set()'),
 ('a release with any store item is not document-only', 'brain/guard.py', 'and v and all(v)}', 'and v and any(v)}'),
 ('the check charges a document-only release no overhead', 'scripts/brain.py', 'tooling |= guard.document_only(col["items"], col["plan"])', 'pass'),
 ('a stale dump fails', 'brain/guard.py', 'if dump_age_min > g["max_dump_age_min"]:', 'if False:'),
 ('a prose placement that contradicts the field fails', 'brain/guard.py', 'if m.group(1).lower() != cur.lower():', 'if False:'),
 ('a conditional is not a claim', 'brain/guard.py', 'if CONDITIONAL.search(note[max(0, m.start() - 80):m.start()]):', 'if False:'),
 ('a time that disagrees with the minutes fails', 'brain/guard.py', 'if t and d.get("minutes") and int(t.group(1)) != d["minutes"]:', 'if False:'),
 ('an umbrella with minutes fails', 'brain/guard.py', 'if ref in kids and d.get("minutes") and "UMBRELLA" in note:', 'if False:'),
 ('a hidden decision fails', 'brain/guard.py', 'and d.get("state") not in DONE and d.get("state") not in ("decision", "input", "removed")):', 'and False):'),
 ('a closed task in a live release fails', 'brain/guard.py', 'if d["state"] == "closed":', 'if False:'),
 ('a release over its cap warns', 'brain/guard.py', 'if cur != "Unassigned" and m > cap:', 'if False:'),
 ('a stale header fails', 'brain/guard.py', 'if age > g["header_max_min"]:', 'if False:'),
 ('the limits come from the settings', 'brain/guard.py', 'g.update((cfg or {}).get("guard", {}))', 'pass'),
 ('a bundle with a wrong checksum is refused', 'brain/bundle.py', 'if bundle.get("sha256") != _digest(c):', 'if False:'),
 ('a bundle with a wrong count is refused', 'brain/bundle.py', 'if isinstance(v, dict) and counts.get(k) != len(v):', 'if False:'),
 ('a bundle with a wrong schema is refused', 'brain/bundle.py', 'if bundle.get("schema") != SCHEMA:', 'if False:'),
 ('an import never overwrites', 'brain/bundle.py', 'if os.path.exists(os.path.join(folder, name)):', 'if False:'),
 ('a damaged bundle is refused whole', 'brain/bundle.py', 'return ({}, problems) if problems else (c, [])', 'return (c, problems)'),
 ('a failed bundle write leaves the old file whole', 'brain/bundle.py', 'fd, tmp = tempfile.mkstemp(dir=d, prefix=".bundle-", suffix=".tmp")', 'fd, tmp = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC), path'),
 ('the degrade path exits three', 'scripts/brain.py', 'return 1 if fails else (3 if degraded else 0)', 'return 1 if fails else 0'),
 ('the degrade path says so', 'scripts/brain.py', 'print(f"DEGRADED: the store was unavailable', 'print(f"x: the store was unavailable'),
 ('an old export still fails the freshness rule', 'scripts/brain.py', 'age = (now - parse_time(stamp)).total_seconds() / 60 if parse_time(stamp) else 10 ** 9', 'age = 0'),
 ('a project with no tests has no test gate', 'brain/install.py', 'if any(os.path.isdir(os.path.join(project, d)) for d in TEST_DIRS):', 'if True:'),
 ("a gate's minutes are never guessed", 'brain/install.py', 'gates.append({"key": "tests", "label": "test suite", "minutes": 0,', 'gates.append({"key": "tests", "label": "test suite", "minutes": 45,'),
 ('a container is only claimed when a file says so', 'brain/install.py', 'container = has("Dockerfile") or has(".gitlab-ci.yml")', 'container = True'),
 ('a second install is refused', 'brain/install.py', 'if os.path.exists(dest) and not upgrade:', 'if False:'),
 ('nothing to upgrade is refused', 'brain/install.py', 'if upgrade and not os.path.exists(dest):', 'if False:'),
 ('a dry run writes nothing', 'brain/install.py', '    if not write:\n        return out + ["dry run', '    if False:\n        return out + ["dry run'),
 ('an existing settings record is kept', 'brain/install.py', 'if not os.path.exists(cfg_path):', 'if True:'),
 ('a failed upgrade puts the previous version back', 'brain/install.py', '        if os.path.exists(prev):\n            os.rename(prev, dest)\n            out.append(', '        if False:\n            os.rename(prev, dest)\n            out.append('),
 ('a failed first install leaves nothing behind', 'brain/install.py', '        shutil.rmtree(dest)\n        if os.path.exists(prev):', '        pass\n        if os.path.exists(prev):'),
 ('compiled caches are not copied', 'brain/install.py', 'COPY_SKIP = shutil.ignore_patterns("__pycache__", "*.pyc", ".state-*", ".bundle-*")', 'COPY_SKIP = None'),
 ('a record the pack would refuse is never written', 'brain/install.py', '        load_config(cfg)\n    except ConfigError as e:', '        pass\n    except ConfigError as e:'),
 ('a refused install exits one', 'scripts/brain.py', 'print(*lines, sep="\\n")\n        return 0 if ok else 1', 'print(*lines, sep="\\n")\n        return 0'),
 ('a locked item the plan never reaches is reported', 'brain/optimiser.py', '        warnings.append(f"{i[\'ref\']}: {why}")\n        stranded.append', '        pass\n        stranded.append'),
 ('a stranded item is listed as waiting', 'brain/optimiser.py', 'for i in waiting] + stranded,', 'for i in waiting],'),
 ('the text plan shows the tooling items', 'scripts/brain.py', 'if t["items"]:   # VH-467', 'if False:   # VH-467'),
 ('a split inside one family is not a duplicate', 'brain/dupes.py', 'if family(a) == family(b) or live[a].get("parent") == live[b].get("parent") and live[a].get("parent"):', 'if False:'),
 ('a recorded relationship is not reported', 'brain/dupes.py', 'if b in (live[a].get("note") or "") or a in (live[b].get("note") or ""):', 'if False:'),
 ('done and removed tasks are not compared', 'brain/dupes.py', 'live = {r: d for r, d in items.items() if d.get("state") not in DONE}', 'live = dict(items)'),
 ('the threshold decides', 'brain/dupes.py', 'if s >= threshold:', 'if True:'),
 ('the title counts more than a template note', 'brain/dupes.py', 'return (" ".join([t, t, t]) + " "', 'return (t + " "'),
 ('a path meant to be new or gone is not reported', 'brain/evidence.py', 'if NEW.search(before) or GONE.search(before) or GONE.search(after):', 'if False:'),
 ('only open tasks are checked', 'brain/evidence.py', 'if d.get("state") not in OPEN:\n            continue\n        seen', 'if False:\n            continue\n        seen'),
 ('wildcards and placeholders are skipped', 'brain/evidence.py', '/[\\w@./-]+\\.', '/[\\w@./*<>-]+\\.'),
 ('a path in any given tree counts', 'brain/evidence.py', 'if not any(os.path.exists(os.path.join(r, p)) for r in repos) and', 'if not os.path.exists(os.path.join(repos[0], p)) and'),
 ('a double extension is read whole', 'brain/evidence.py', '[\\w@./-]+\\.[A-Za-z]{1,5})', '[\\w@./-]*?\\.[A-Za-z]{1,5})'),
 ('trailing punctuation is not part of a path', 'brain/evidence.py', '\\.[A-Za-z]{1,5})(?::', '\\.[A-Za-z]{1,5}[.,;]?)(?::'),
 ('duplicates make the command exit one', 'scripts/brain.py', 'return 1 if pairs else 0', 'return 0'),
 ('a missing path makes the command exit one', 'scripts/brain.py', 'return 1 if rows else 0', 'return 0'),
 ('a tree that is not a folder is refused', 'scripts/brain.py', '        if not os.path.isdir(r):', '        if False:'),
 ('a stale test count in SKILL.md fails', 'SKILL.md', 'runs 197 tests', 'runs 196 tests'),
 ('a stale mutation count in SKILL.md fails', 'SKILL.md', '(200 of 200 caught', '(199 of 200 caught'),
 ('an unknown intake status fails', 'brain/guard.py', 'if st not in INTAKE_OPEN + INTAKE_SHUT:', 'if False:'),
 ('an intake outcome naming a release fails', 'brain/guard.py', 'if rel.search(out):', 'if False:'),
 ('an actioned open intake fails', 'brain/guard.py', 'if x.get("ref") or named_by:', 'if False:'),
 ('a stale open intake fails', 'brain/guard.py', 'if age > g["intake_max_min"]:', 'if False:'),
 ('the intake wait limit comes from the settings', 'brain/guard.py', 'if age > g["intake_max_min"]:', 'if age > 120:'),
 ('a resolved intake with no date fails', 'brain/guard.py', 'if not x.get("resolvedAt"):', 'if False:'),
 ('a logged intake with no ref fails', 'brain/guard.py', 'if not x.get("ref"):', 'if False:'),
 ('a logged ref not on the board fails', 'brain/guard.py', 'elif x["ref"] not in items:', 'elif False:'),
 ('a rejected intake with no outcome fails', 'brain/guard.py', 'elif not out:', 'elif False:'),
 ('a link to a ghost thread fails', 'brain/guard.py', 'if l.get(end) not in threads:', 'if False:'),
 ('two prime threads fail', 'brain/guard.py', 'if devs and len(masters) != 1:', 'if False:'),
 ('a prime that is not first in order fails', 'brain/guard.py', 'if m != first:', 'if False:'),
 ('an unfed development thread fails', 'brain/guard.py', 'if (b, R["feeds"], d) not in have:', 'if False:'),
 ('a thread with no route back fails', 'brain/guard.py', 'if (d, R["raises"], b) not in have:', 'if False:'),
 ('a thread not working hand in glove fails', 'brain/guard.py', 'if (d, R["glove"], m) not in have:', 'if False:'),
 ('uninstructed documentation fails', 'brain/guard.py', 'if m and (m, R["instructs"], d) not in have:', 'if False:'),
 ('documentation with no route to backlog fails', 'brain/guard.py', 'if (d, R["passes"], b) not in have:', 'if False:'),
 ('the relation words come from the settings', 'brain/guard.py', 'g["relations"] = dict(DEFAULTS["relations"], **((cfg or {}).get("guard", {}).get("relations") or {}))', 'g["relations"] = dict(DEFAULTS["relations"])'),
 ('an overhead that outweighs the build warns', 'brain/guard.py', 'if b < g["overhead_min"]:', 'if False:'),
 ('only release or rollup rows are lane samples', 'brain/guard.py', 'if r.get("kind") not in ("release", "rollup"):', 'if False:'),
 ('close lane samples agree and far ones do not', 'brain/guard.py', 'agree = len(paces) >= 2 and paces[-1] <= paces[0] * 1.2', 'agree = True'),
 ('the state block is replaced in place', 'brain/guard.py', 'if BEGIN in s:', 'if False:'),
 ('the state block is never written from a stale read', 'scripts/brain.py', 'if a.state_block and not any(f.startswith("STALE DUMP") for f in fails):', 'if a.state_block:'),
 ('the command reads the intake collection', 'scripts/brain.py', 'if "intake" in col:', 'if False:'),
 ('the command reads the thread structure', 'scripts/brain.py', 'if "threads" in col and "links" in col:', 'if False:'),
 ('an open task carrying supersededBy fails', 'brain/guard.py', 'if d.get("state") in OPEN:\n            fails.append(f"{ref}: superseded', 'if False:\n            fails.append(f"{ref}: superseded'),
 ('a supersededBy naming no board item fails', 'brain/guard.py', 'if isinstance(by, str) and REF.match(by) and by not in items:', 'if False:'),
 ('a sentence in supersededBy is not read as a ref', 'brain/guard.py', 'REF.match(by) and by not in items', 'by not in items'),
 ('the duplicate threshold comes from the settings', 'brain/guard.py', 'threshold = ((cfg or {}).get("guard", {}) or {}).get("dupes_threshold", 0.55)', 'threshold = 0.55'),
 ('a declared pair is not reported', 'brain/dupes.py', 'if _declared(live[a], b) or _declared(live[b], a):', 'if False:'),
 ('a declaration on either side counts', 'brain/dupes.py', 'if _declared(live[a], b) or _declared(live[b], a):', 'if _declared(live[a], b):'),
 ('relatesTo is a declaration as well as distinctFrom', 'brain/dupes.py', 'for key in ("distinctFrom", "relatesTo"):', 'for key in ("distinctFrom",):'),
 ('a list of declared refs counts', 'brain/dupes.py', 'refs = v if isinstance(v, list) else', 'refs = [] if isinstance(v, list) else'),
 ('a file on a fetched branch counts', 'brain/evidence.py', ' and not any(p in t for t in trees):', ':'),
 ('fetched branches are read as well as HEAD', 'brain/evidence.py', '    for r in refs:\n        try:', '    for r in []:\n        try:'),
 ('branch paths are read from the repository root', 'brain/evidence.py', '"ls-tree", "-r", "-z", "--full-tree", "--name-only"', '"ls-tree", "-r", "-z", "--name-only"'),
 ('the check runs the supersession record', 'scripts/brain.py', 'fails += guard.check_superseded(col["items"])', 'pass'),
 ('the check runs the duplicate scan', 'scripts/brain.py', 'fails += guard.check_duplicates(col["items"], cfg)', 'pass'),
 ('the check runs the evidence check', 'scripts/brain.py', '                    fails += found', '                    pass'),
 ('shared-only leaves the additions out', 'scripts/brain.py', 'if not a.shared_only:', 'if True:'),
 ('evidence can be switched off in the settings', 'scripts/brain.py', 'if g.get("evidence", True) is not False:', 'if True:'),
 ('the check says when evidence could not run', 'scripts/brain.py', 'warns.append("EVIDENCE not run', 'str("EVIDENCE not run'),
 ('the hourly path counts the trees git read', 'scripts/brain.py', '[t for _, t in got["trees"]]', '[]'),
 ('the hourly path reads the repository that holds the pack', 'scripts/brain.py', 'got = git_trees(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."),', 'got = git_trees(os.devnull,'),
 ('--repo reaches the evidence check', 'scripts/brain.py', 'col["items"], a.repo, [], "is in none of the folders given"', 'col["items"], [], [], "is in none of the folders given"'),
 ('the duplicate threshold reaches the command', 'scripts/brain.py', 'check_duplicates(col["items"], cfg)', 'check_duplicates(col["items"])'),
 ('the working tree counts on the hourly path', 'scripts/brain.py', '[got["top"]] if got["top"] else []', '[]'),
 ('with only HEAD read a missing path warns', 'scripts/brain.py', 'elif n == 1:', 'elif False:'),
 ('a branch that cannot be read is warned about', 'scripts/brain.py', 'warns += [f"EVIDENCE could not read {r}', '[f"EVIDENCE could not read {r}'),
 ('every fetched branch counts by default', 'scripts/brain.py', 'or ["refs/remotes/origin/"]', 'or ["refs/remotes/origin/claude/"]'),
 ('the branch patterns come from the settings', 'scripts/brain.py', 'g.get("evidence_refs") or', 'None or'),
 ('another branch counts only for what it added', 'brain/evidence.py', 'd = git("diff", "--name-only", "-z", "--no-renames", "--diff-filter=A", "HEAD..." + r)', 'd = git("ls-tree", "-r", "-z", "--full-tree", "--name-only", r)'),
 ('an unreadable branch is listed, never guessed', 'brain/evidence.py', '            out["unread"].append(r)', '            pass'),
 ('paths are read NUL-separated', 'brain/evidence.py', '"diff", "--name-only", "-z", "--no-renames"', '"diff", "--name-only", "--no-renames"'),
 ('a path may not end before a wildcard', 'brain/evidence.py', '(?![\\w/*<>{-])', '(?![\\w/-])'),
 ('a declaration may be a comma list', 'brain/dupes.py', 'str(v).split(",") if isinstance(v, str)', '[v] if isinstance(v, str)'),
 ('a declaration is read in any case', 'brain/dupes.py', 'want = str(other).strip().upper()', 'want = str(other)'),
 ('the page and the pack hold the same defaults', 'brain/board.py', '"organisation": "Bluestaq Limited",', '"organisation": "Bluestaq Ltd",'),
 ('the board problems reach the settings loader', 'brain/model.py', '    problems += section_problems(cfg)', '    pass'),
 ('a reserved gate key is refused', 'brain/board.py', '        if k in RESERVED_GATES:', '        if False:'),
 ('a store with no name is refused', 'brain/board.py', '_text(s.get("name"), 40, "board.store.name", problems, empty_ok=False)', 'None'),
 ('part minutes are refused for the page', 'brain/board.py', ' or v != int(v) or ', ' or '),
 ('the store job is dropped without a store', 'brain/board.py', 'if j.get("when") == "store" and not s.get("store"):', 'if False:'),
 ('hours read the same in the pack as on the page', 'brain/board.py', 'return f"{round(m / 60, 2):g}"', 'return f"{m // 60}"'),
 ('the overhead words round to the nearer hour', 'brain/board.py', 'if r < 30 else', 'if r <= 30 else'),
 ("the seed adds the store's upload gate", 'brain/board.py', '    if s["store"]:\n        writes.append(', '    if False:\n        writes.append('),
 ('the seed opens the horizon behind the current release', 'brain/board.py', 'for i in range(s["horizon"] + 1)]', 'for i in range(1)]'),
 ('a seed over one batch is refused', 'brain/board.py', '    if len(writes) > 50:', '    if False:'),
 ('the text guide is filled', 'brain/guide.py', '    g = fill_guide(guide[audience], settings)', '    g = guide[audience]'),
 ('the page falls back when a field fails its check', 'assets/board/board.html', 'const pick = (v, dv, ok) => ok(v) ? v : dv;', 'const pick = (v, dv, ok) => v ?? dv;'),
 ('null switches the store off on the page', 'assets/board/board.html', 'store: x.store === null ? null : st', 'store: st'),
 ('a budget with the floor over the cap falls back', 'assets/board/board.html', ' && b.floorMin <= b.capMin ? {floorMin', ' ? {floorMin'),
 ('the page fills the guide tokens', 'assets/board/board.html', 'return String(t).replace(/\\{(floor|cap|ref|source|overhead)\\}/g, (_, k) => v[k]);', 'return String(t);'),
 ('the page drops the store job without a store', 'assets/board/board.html', 'jobs: g.jobs.filter(j => j.when !== "store" || s.store)', 'jobs: g.jobs.filter(j => true)'),
 ('the page reads hours as the pack does', 'assets/board/board.html', 'const hoursText = m => String(Math.round(m / 60 * 100) / 100);', 'const hoursText = m => String(Math.floor(m / 60));'),
 ('the approvals patch refuses a missing or repeated anchor', 'brain/approvals_patch.py', '    if n != 1:', '    if False:'),
 ('the approvals patch refuses a second apply', 'brain/approvals_patch.py', '    if has(html):\n        raise', '    if False:\n        raise'),
 ('the approvals patch adds the render hook', 'brain/approvals_patch.py', 'html = html.replace(a_hook, "renderThreads(); renderDecQ(); renderAppr(); }); }", 1)', 'pass'),
 ('only the header and the settings leave with an export', 'brain/bundle.py', 'if name == "board" and f[:-5] not in BOARD_DOCS:', 'if False:'),
 ('check reads the header from the dump', 'scripts/brain.py', 'meta = (col.get("board") or {}).get("meta")', 'meta = None'),
 ('selfcheck counts what it skipped', 'scripts/brain.py', 'f"{len(res.skipped)} skipped")', 'f"")'),
 ('a refused record exits two from board seed', 'scripts/brain.py', '        print("The settings record is refused:", *e.problems, sep="\\n  ", file=sys.stderr)\n        return 2\n    except (ValueError, OSError) as e:\n        print("cannot build it:"', '        print("The settings record is refused:", *e.problems, sep="\\n  ", file=sys.stderr)\n        return 0\n    except (ValueError, OSError) as e:\n        print("cannot build it:"'),
 ('relay --to checks one poke', 'scripts/brain.py', '    if a.dst:\n        try:', '    if False:\n        try:'),
 ('idle pauses on the third quiet check', 'brain/idle.py', '    pause = n >= threshold', '    pause = False'),
 ('idle refuses a board with no items', 'brain/idle.py', "        if name in ('items', 'plan') and not docs:", '        if False:'),
 ('a Dockerfile gate is never keyed build', 'brain/install.py', '        gates.append({"key": "container", "label": "container build",', '        gates.append({"key": "build", "label": "container build",'),
 ("the page's limits are checked where the board is built", 'brain/board.py', '    if problems:\n        raise ConfigError(problems)', '    if False:\n        raise ConfigError(problems)'),
 ('a gate key the store would refuse is refused', 'brain/board.py', 'elif not (isinstance(k, str) and DOC_ID.match(k)):', 'elif False:'),
 ('an unknown board setting is refused', 'brain/board.py', 'for k in sorted(set(b) - SECTION_KEYS):', 'for k in []:'),
 ('the board keeps V release names', 'brain/board.py', 'if r.get("naming") != "V{major}.{minor}" or', 'if False and'),
 ('names are counted as the page counts them', 'brain/board.py', '_units(v) > limit', 'len(v) > limit'),
 ('a project name too long for the page is refused at seed time', 'brain/board.py', '_text(p.get("name"), 80, "project.name, for the board page,", problems, empty_ok=False)', 'None'),
 ('nothing measured is never called measured', 'brain/board.py', 'return f"fixed work for checks, packaging and {end}, not yet measured"', 'return f"a measured amount of fixed work for checks, packaging and {end}"'),
 ('the guide says release without a store', 'brain/board.py', 'end = "upload" if store else "release"', 'end = "upload"'),
 ("the page's guide says release without a store", 'assets/board/board.html', 'const end = store ? "upload" : "release";', 'const end = "upload";'),
 ("the guide's patch needs the settings block", 'brain/page_patch.py', 'if "/*SETTINGS:BEGIN*/" not in html:', 'if False:'),
 ('an upgrade names what stops a board', 'brain/install.py', 'out += [f"before seeding a board from {CONFIG}: {p}" for p in page_problems(kept)]', 'pass'),
 ('guide --config reports an unreadable record', 'scripts/brain.py', '                print("cannot read the settings record:", e, file=sys.stderr)\n                return 2', '                print("cannot read the settings record:", e, file=sys.stderr)\n                return 0'),
]
BOARD = os.path.abspath(os.path.join(ROOT, "..", "..", "board"))
SUITE = [sys.executable, "-W", "ignore", "-m", "unittest", "discover", "-s", "tests"]


def copy_from(root, board):
    """The pack in its place in a project, with the project's board folder beside it when there is one. Since VH-584 the page and
    its helpers ship inside the pack, so no test needs that folder; it is copied so the copy looks like the project it came from."""
    tmp = tempfile.mkdtemp()
    pack = os.path.join(tmp, ".claude", "skills", "backlog-brain")
    shutil.copytree(root, pack, ignore=shutil.ignore_patterns("__pycache__"))     # this file too: test_docs counts its rows
    if board and os.path.isdir(board):
        shutil.copytree(board, os.path.join(tmp, ".claude", "board"), ignore=shutil.ignore_patterns("__pycache__"))
    return tmp, pack


def suite(tmp, pack):
    # Everything the suite writes to a temp folder lands inside this copy and goes with it; the browser test is left to selftest.
    return subprocess.run(SUITE, cwd=pack, capture_output=True, text=True, env=dict(os.environ, TMPDIR=tmp, BRAIN_SKIP_BROWSER="1"))


def one(m):
    name, path, old, new = m
    tmp, pack = copy_from(SNAP_PACK, SNAP_BOARD)
    try:
        f = os.path.join(pack, path)
        src = open(f).read()
        if src.count(old) != 1:
            return False, f"ANCHOR  {name}: matched {src.count(old)} places, so it proves nothing"
        open(f, "w").write(src.replace(old, new))
        ok = suite(tmp, pack).returncode != 0
        return ok, ("RED   " if ok else "GREEN ") + name + ("" if ok else "   <-- the suite did not notice")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# One snapshot, taken once: the baseline and every mutation are built from it, so an edit made while this runs cannot reach a
# mutated copy the baseline never saw (VH-377 review).
SNAP, SNAP_PACK = copy_from(ROOT, BOARD)
SNAP_BOARD = os.path.join(SNAP, ".claude", "board")
try:
    tmp, pack = copy_from(SNAP_PACK, SNAP_BOARD)
    try:
        base = suite(tmp, pack)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if base.returncode != 0:
        print("BASELINE RED: the suite fails in the copy with no mutation applied, so no red result below could prove anything")
        print("\n".join(l for l in base.stderr.splitlines() if l.startswith(("FAIL:", "ERROR:"))))
        print(base.stderr[-2000:])
        sys.exit(1)
    print("baseline green: the unmutated suite passes in the copy")
    with ThreadPoolExecutor(max(1, min(3, (os.cpu_count() or 2) - 1))) as ex:
        results = list(ex.map(one, M))
finally:
    shutil.rmtree(SNAP, ignore_errors=True)
bad = 0
for ok, line in results:
    print(line)
    bad += 0 if ok else 1
print(f"\n{len(M) - bad} of {len(M)} mutations were caught")
sys.exit(1 if bad else 0)
