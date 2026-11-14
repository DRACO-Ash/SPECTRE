"""The freshness guard, generalised (VH-366-E): refuses a stale read and flags a board that has gone wrong.

The Vendor Fishing copy is .claude/board/board_check.py; this one takes everything project-specific from the settings
record, so it works on any board. It returns what it found and holds no state between calls.
FAILS stop the run: a dump older than the limit, a note that says where a task is placed when the release field says
otherwise, a time field that disagrees with the minutes, an umbrella that still carries minutes beside its children, a
decision nobody can see, a board header that is older than the limit.
WARNINGS never stop it: a release over its cap (the cap is a person's to manage), a paused sync, a finished task still
shown in a live release.
"""
import datetime
import re

DONE = ("built", "closed", "released", "done")
OPEN = ("open", "allocated", "needscheck", "decision", "input", "answered", "inbuild", "queued", "held", "blocked", "needscost")
DEFAULTS = {"max_dump_age_min": 15, "header_max_min": 120, "release_regex": r"\b[Vv]\d+(?:\.\d+)+\b", "intake_max_min": 120,
            "relations": {"feeds": "feeds work to", "raises": "passes back tasks it cannot solve in the current release to",
                          "prime": "is the prime development thread for", "glove": "works hand in glove with",
                          "instructs": "instructs", "passes": "passes tasks to"}}
CONDITIONAL = re.compile(r"\b(if|would|unless|when)\b", re.I)


def settings(cfg):
    g = dict(DEFAULTS)
    g.update((cfg or {}).get("guard", {}))
    g["cap_min"] = ((cfg or {}).get("releases", {}) or {}).get("cap_min")
    r = (cfg or {}).get("releases", {}) or {}
    g["pace"], g["overhead_min"] = r.get("pace", 1.0), r.get("overhead_min", 0)
    g["relations"] = dict(DEFAULTS["relations"], **((cfg or {}).get("guard", {}).get("relations") or {}))
    return g


def release_names(plan):
    out = {k: v.get("name", k) for k, v in plan.items() if k != "current"}
    out["backlog"] = "Unassigned"
    return out


def check(items, plan, cfg=None, dump_age_min=0, meta=None, now=None):
    """Returns (fails, warnings, rows) where rows is {release name: [open items, priced minutes]}."""
    g = settings(cfg)
    place = re.compile(r"\b(?:was moved to|moved to|moves to|now in|placed in|sits in|stays in)\s+(" + g["release_regex"].replace("\\b", "") + ")", re.I)
    nm, fails, warns, rows = release_names(plan), [], [], {}
    if dump_age_min > g["max_dump_age_min"]:
        fails.append(f"STALE DUMP: the items dump is {dump_age_min:.0f} min old (limit {g['max_dump_age_min']}). Read the board again first.")
    released = {k for k, v in plan.items() if v.get("status") == "released"}
    for ref, d in sorted(items.items()):
        if d.get("state") in DONE and d.get("release") not in released:
            where = nm.get(d.get("release"), d.get("release"))
            if d["state"] == "closed":
                fails.append(f"{ref}: closed but still shown in {where}; move it to the archive")
            else:
                warns.append(f"{ref}: {d['state']} but still shown in {where}; if it shipped, move it to the release that shipped it")
        dec = d.get("decision")
        if (isinstance(dec, dict) and dec.get("options") and not d.get("decisionAnswer")
                and d.get("state") not in DONE and d.get("state") not in ("decision", "input", "removed")):
            fails.append(f"{ref}: has an unanswered decision but its state is {d.get('state')!r}, so nobody sees the question; set it to input")
    kids = {}
    for ref, d in items.items():
        if d.get("parent"):
            kids.setdefault(d["parent"], []).append(ref)
    for ref, d in sorted(items.items()):
        if d.get("state") not in OPEN:
            continue
        rel = d.get("release") or "backlog"
        cur = nm.get(rel, rel)
        r = rows.setdefault(cur, [0, 0])
        r[0] += 1
        r[1] += d.get("minutes") or 0
        note = d.get("note") or ""
        for m in place.finditer(note):
            if CONDITIONAL.search(note[max(0, m.start() - 80):m.start()]):
                continue   # a conditional is not a claim about today
            if m.group(1).lower() != cur.lower():
                fails.append(f'{ref}: note says "{m.group(0)}" but the release field is {cur}')
        t = re.match(r"\s*(\d+)m\b", d.get("time") or "")
        if t and d.get("minutes") and int(t.group(1)) != d["minutes"]:
            fails.append(f"{ref}: time field starts {t.group(1)}m but minutes is {d['minutes']}")
        if ref in kids and d.get("minutes") and "UMBRELLA" in note:
            fails.append(f"{ref}: umbrella still carries {d['minutes']}m beside its children {', '.join(sorted(kids[ref]))}")
    cap = g["cap_min"]
    if cap:
        for cur, (n, m) in sorted(rows.items()):
            if cur != "Unassigned" and m > cap:
                warns.append(f"{cur}: {m} priced minutes is over the {cap} cap (ADVISORY, the cap is a person's to manage)")
    if meta and now and meta.get("syncPaused"):
        warns.append(f"sync is PAUSED since {meta.get('pausedAt')}: nothing changed in {meta.get('idleChecks')} checks")
    elif meta and now and meta.get("updatedAt"):
        up = datetime.datetime.fromisoformat(meta["updatedAt"].replace("Z", "+00:00"))
        age = (now - up).total_seconds() / 60
        if age > g["header_max_min"]:
            fails.append(f"BOARD HEADER STALE: meta.updatedAt is {age / 60:.1f}h old. Every board write must end by setting it.")
    return fails, warns, rows


# ---- Intake, threads, forecast and the state block (VH-366-H: the pack does everything board_check.py does) ----
INTAKE_OPEN = ("submitted", "investigating")
INTAKE_SHUT = ("logged", "rejected")
BEGIN, END = "<!-- STATE:BEGIN -->", "<!-- STATE:END -->"


def check_intake(intake, items, now, cfg=None):
    """Intake must not hold stale or actioned entries: an entry whose item exists, or that waited past the limit, fails."""
    g, fails = settings(cfg), []
    rel = re.compile(g["release_regex"])
    notes = {i: " ".join(str(d.get(k) or "") for k in ("note", "note2", "note3", "note4", "task")) for i, d in items.items()}
    for k, x in sorted(intake.items()):
        st, label = x.get("status"), f"intake {k[:8]} ({(x.get('title') or '').strip()[:40]})"
        if st not in INTAKE_OPEN + INTAKE_SHUT:
            fails.append(f"{label}: status {st!r} is not submitted, investigating, logged or rejected, so the page cannot place it")
            continue
        out = x.get("outcome") or ""
        if rel.search(out):
            fails.append(f'{label}: the outcome names a release ("{rel.search(out).group(0)}"); the item it became carries the live placement')
        named_by = sorted(i for i, t in notes.items() if k in t)
        if st in INTAKE_OPEN:
            if x.get("ref") or named_by:
                fails.append(f"{label}: still {st} but already actioned as {x.get('ref') or ', '.join(named_by)}; close it as logged")
            sub = x.get("submittedAt")
            if sub and now:
                age = (now - datetime.datetime.fromisoformat(sub.replace("Z", "+00:00"))).total_seconds() / 60
                if age > g["intake_max_min"]:
                    fails.append(f"{label}: waiting {age / 60:.1f}h with no triage (limit {g['intake_max_min'] / 60:.0f}h); the hourly sync must triage it")
        else:
            if not x.get("resolvedAt"):
                fails.append(f"{label}: {st} with no resolvedAt, so the history cannot order it")
            if st == "logged":
                if not x.get("ref"):
                    fails.append(f"{label}: logged with no ref to the item it became")
                elif x["ref"] not in items:
                    fails.append(f"{label}: logged as {x['ref']}, which is not on the board")
            elif not out:
                fails.append(f"{label}: rejected with no outcome, so the owner is never told why")
    return fails


def check_threads(threads, links, cfg=None):
    """Thread structure: Backlog feeds every development thread, each passes back what it cannot solve, the first in order is
    the one prime thread, the others work hand in glove with it, and it instructs Documentation, which passes tasks to Backlog."""
    R, fails = settings(cfg)["relations"], []
    have = {(l.get("from"), l.get("kind"), l.get("to")) for l in links.values()}
    for k, l in sorted(links.items()):
        for end in ("from", "to"):
            if l.get(end) not in threads:
                fails.append(f"link {k}: {end} {l.get(end)!r} is not a thread on the board")
    role = lambda r: sorted(t for t, d in threads.items() if d.get("role") == r)
    backlog, devs, docs = role("backlog"), role("development"), role("documentation")
    if len(backlog) != 1:
        return fails + [f"threads: expected exactly one backlog thread, found {len(backlog)}"]
    b = backlog[0]
    masters = sorted({f for (f, kd, t) in have if kd == R["prime"] and f in devs})
    if devs and len(masters) != 1:
        fails.append(f"threads: expected exactly one prime development thread among the development threads, found {len(masters)}")
    m = masters[0] if len(masters) == 1 else None
    if devs and m:
        first = min(devs, key=lambda t: (threads[t].get("order", 1e9), t))
        if m != first:
            fails.append(f"threads: {threads[m].get('name', m)} is the prime development thread but {threads[first].get('name', first)} is first in order; Development 1 is always the prime")
    for d in devs:
        n = threads[d].get("name", d)
        if (b, R["feeds"], d) not in have:
            fails.append(f"{n}: Backlog does not feed work to it")
        if (d, R["raises"], b) not in have:
            fails.append(f"{n}: it has no way to pass back to Backlog what it cannot solve in the current release")
        if m and d != m:
            if (m, R["prime"], d) not in have:
                fails.append(f"{n}: {threads[m].get('name', m)} is not its prime development thread")
            if (d, R["glove"], m) not in have:
                fails.append(f"{n}: it does not work hand in glove with the prime development thread")
    for d in docs:
        n = threads[d].get("name", d)
        if m and (m, R["instructs"], d) not in have:
            fails.append(f"{n}: the prime development thread does not instruct it")
        if (d, R["passes"], b) not in have:
            fails.append(f"{n}: it cannot pass tasks to Backlog")
    return fails


def _hm(m):
    return f"{int(m // 60)}h{int(m % 60):02d}"


def overhead_warnings(rows, tooling=(), cfg=None):
    """Release overhead must not outweigh the build; advisory, raised at planning."""
    g, out = settings(cfg), []
    for k, (n, m) in sorted(rows.items()):
        if k == "Unassigned" or k in tooling:
            continue
        b = m * g["pace"]
        if b < g["overhead_min"]:
            out.append(f"{k}: release overhead ({_hm(g['overhead_min'])}) outweighs its build forecast ({_hm(b)}); raise it with the owner at planning, not at the freeze")
    return out


# VH-468: kinds that ship no store artefact. The optimiser already takes research and investigation off the release path
# (model.OFF_PATH_KINDS); a document is the same for the forecast, since a report is written, not uploaded.
DOCUMENT_KINDS = ("research", "investigation", "document")


def document_only(items, plan):
    """Release names whose open items are all research, investigation or document work: no store upload, so no release overhead."""
    nm, seen = release_names(plan), {}
    for d in items.values():
        if d.get("state") not in OPEN:
            continue
        name = nm.get(d.get("release") or "backlog", d.get("release"))
        seen.setdefault(name, []).append(d.get("kind") in DOCUMENT_KINDS)
    return {k for k, v in seen.items() if k != "Unassigned" and v and all(v)}


def lane_paces(acc):
    """Elapsed build minutes per priced minute for each accuracy row of kind release or rollup that records lanes, priced and elapsed."""
    out = []
    for k, r in sorted(acc.items()):
        if r.get("kind") not in ("release", "rollup"):
            continue
        if all(isinstance(r.get(f), (int, float)) and not isinstance(r.get(f), bool) and r[f] > 0 for f in ("lanes", "priced", "elapsed")):
            out.append((k, int(r["lanes"]), r["elapsed"] / r["priced"]))
    return out


def lane_lines(rows, samples, tooling=(), cfg=None):
    """The forecast at the measured elapsed pace, shown beside the one-lane forecast and never instead of it. Two samples agree within 20 percent."""
    g = settings(cfg)
    if not samples:
        return ["LANE PACE: no release row records lanes, priced and elapsed minutes yet, so only the one-lane forecast is shown"]
    paces = sorted(p for _, _, p in samples)
    mid = paces[len(paces) // 2] if len(paces) % 2 else (paces[len(paces) // 2 - 1] + paces[len(paces) // 2]) / 2
    agree = len(paces) >= 2 and paces[-1] <= paces[0] * 1.2
    out = [f'LANE PACE: {len(samples)} release(s) measured ({", ".join(f"{k} {n} lanes {p:.2f}" for k, n, p in samples)}), '
           f'median {mid:.2f} of priced minutes against {g["pace"]} for one lane; '
           + ("they agree, so it is the better forecast" if agree else "not yet agreed, so the one-lane forecast stands and this is shown beside it")]
    for k, (n, m) in sorted(rows.items()):
        if k == "Unassigned" or k in tooling:
            continue
        out.append(f"LANE PACE {k}: {_hm(m * mid + g['overhead_min'])} at the measured elapsed pace, {_hm(m * g['pace'] + g['overhead_min'])} at one lane")
    return out


def table(rows, tooling=(), cfg=None):
    g = settings(cfg)
    out = ["| Release | Open items | Priced minutes | Forecast to upload |", "|---|---|---|---|"]
    for k, (n, m) in sorted(rows.items(), key=lambda kv: (kv[0] == "Unassigned", kv[0])):
        if k == "Unassigned":
            out.append(f"| {k} | {n} | {m} | off the release path |")
        elif k in tooling:
            out.append(f"| {k} | {n} | {m} | {_hm(m * g['pace'])} build, no store upload |")
        else:
            out.append(f"| {k} | {n} | {m} | {_hm(m * g['pace'] + g['overhead_min'])} |")
    return "\n".join(out)


def write_block(path, rows, stamp, extra="", tooling=(), cfg=None):
    """Rewrites the state block of a markdown file between its two markers, or inserts it under the first heading when absent."""
    s = open(path).read()
    block = (f"{BEGIN}\n**STATE AT A GLANCE, read from the board at {stamp}. This block is the only current-status statement in this file; "
             f"every dated record below it is history and may describe a state that has since changed.** "
             f"Regenerate with `brain.py check --state-block`.\n\n{table(rows, tooling, cfg)}\n\n{extra}\n{END}\n")
    if BEGIN in s:
        s = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n", lambda m: block, s, flags=re.S)
    else:
        first, _, rest = s.partition("\n\n")
        s = first + "\n\n" + block + "\n" + rest
    open(path, "w").write(s)


# ---- Keeping the backlog accurate (VH-377): what the hourly check adds to catch duplicates, overtaken tasks and stale citations ----
REF = re.compile(r"^[A-Za-z]+-\d+(?:-[A-Za-z0-9]+)*$")


def check_superseded(items):
    """C, the supersession record: a task a decision or a build has overtaken carries `supersededBy` (a ref, or a sentence naming the
    decision). An OPEN task that carries it fails, because the board would otherwise show work nobody should start; so does one that
    names a ref the board does not hold, because then nobody can follow the record."""
    fails = []
    for ref, d in sorted(items.items()):
        by = d.get("supersededBy")
        if not by:
            continue
        if d.get("state") in OPEN:
            fails.append(f"{ref}: superseded by {by} but still open; close it as superseded, or clear supersededBy if it is still wanted")
        if isinstance(by, str) and REF.match(by) and by not in items:
            fails.append(f"{ref}: supersededBy names {by}, which is not on the board")
    return fails


def check_duplicates(items, cfg=None):
    """A, run by the hourly check: open tasks that read like the same job fail until a person folds one into the other (Merge into on
    the board) or records that they are different (`distinctFrom`) or related on purpose (`relatesTo`). The threshold is the settings
    record's `guard.dupes_threshold`, default 0.55."""
    from .dupes import find
    threshold = ((cfg or {}).get("guard", {}) or {}).get("dupes_threshold", 0.55)
    return [f"{a} and {b} read like the same job ({s:.2f}); fold one into the other with Merge into, or record distinctFrom on one"
            for s, a, b in find(items, threshold, top=50)]


def check_evidence(items, repos=(), trees=(), where="is not on disk or on any branch read"):
    """D, run by the hourly check: an open task citing a path that is in none of the folders and none of the git trees given. The
    FAIL says what was read, so it never claims a branch it did not read lacks the file."""
    from .evidence import missing
    return [f"{ref}: cites {p}, which {where}; correct the note, or record supersededBy if the work has gone"
            for ref, p in missing(items, repos, trees)]
