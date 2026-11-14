"""Start a Claude Code thread from the board, and brief it.

A new thread starts with no memory, so everything it needs is in its brief: who it is, how it relates to the other
threads, which board and repository it works in, which branch it may write, and which lane of work is its own. This
module only builds the request; the session itself is started by whoever holds the session tool (the Backlog thread,
or the page with the connector), so the same brief serves both routes and can be tested without starting anything.
"""
import re

ROLE_LABELS = {"backlog": "Backlog", "development": "Development", "research": "Research",
               "documentation": "Documentation", "other": "Other"}
SESSION_RE = re.compile(r"session_[A-Za-z0-9]+")


def slug(text):
    s = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    return s or "thread"


def branch_for(thread, prefix="claude"):
    """The one branch a development thread may write. Derived from its name and id, never from free text."""
    return f"{prefix}/{slug(thread['name'])}-{slug(thread.get('id', ''))[:12]}".rstrip("-")


def thread_link(result):
    """The board link for a started thread, from the session tool's result. Shape seen 2026-10-01: {"ccr": {"id": "session_..."}}."""
    sid = ((result or {}).get("ccr") or {}).get("id") or ""
    if not SESSION_RE.fullmatch(sid):
        raise ValueError("the session tool did not return a session id")
    return f"https://claude.ai/code/{sid}"


def session_id_of(url):
    m = SESSION_RE.search(url or "")
    return m.group(0) if m else None


def backlog_session(threads):
    """The session id of the Backlog thread, or None. Every other thread wakes it with this."""
    for t in threads:
        if t.get("role") == "backlog":
            sid = session_id_of(t.get("url"))
            if sid:
                return sid
    return None


def relations(thread, threads, links):
    by = {t["id"]: t for t in threads}
    out = []
    for l in links:
        if l["from"] == thread["id"] and l["to"] in by:
            out.append(("out", l["kind"], by[l["to"]]))
        elif l["to"] == thread["id"] and l["from"] in by:
            out.append(("in", l["kind"], by[l["from"]]))
    return out


def lanes_disjoint(lanes_by_thread):
    """lanes_by_thread: {thread name: [files]}. Returns the files two threads would both write."""
    seen, clash = {}, []
    for name, files in sorted(lanes_by_thread.items()):
        for f in files:
            if f in seen and seen[f] != name:
                clash.append((f, seen[f], name))
            seen.setdefault(f, name)
    return clash


def brief(thread, threads, links, lane_items, project, board_url, repo, first_task=None, base=None):
    if not thread.get("name"):
        raise ValueError("a thread needs a name before it can be started")
    role = ROLE_LABELS.get(thread.get("role"), "Other")
    rel = relations(thread, threads, links)
    lines = [f"You are {thread['name']}, a {role} thread of the {project} project. You have no memory of earlier work; this brief is all you start with.", ""]
    lines.append("HOW YOU RELATE TO THE OTHER THREADS")
    if rel:
        for direction, kind, other in rel:
            sid = session_id_of(other.get("url"))
            who = f"{other['name']} ({sid})" if sid else other["name"]
            lines.append(f"- {thread['name']} {kind} {who}" if direction == "out" else f"- {who} {kind} {thread['name']}")
    else:
        lines.append("- none recorded yet")
    # THE OWNER'S ETHOS (2026-10-07), carried by every brief so every thread starts with it.
    lines += ["", "HOW YOU WORK",
              "- Best speed and efficiency, balanced with quality and release standards: zero waste, zero duplication.",
              "- Never run a check twice on the same tree: reuse a stamp that still matches. Never wait idle: book a short check-in and run the next independent step.",
              "- Work in parallel with the other threads wherever files do not collide. Nothing new enters a frozen release; it goes to the next one. The standards are never lowered."]
    lines += ["", "WHERE YOU WORK",
              f"- Repository: {repo}. Read CLAUDE.md first; its rules apply to you.",
              f"- Board (the backlog, the plan and the threads): {board_url}. Read it with the ArtifactData tool.",
              "- docs/BACKLOG.md opens with a STATE block that is the only current-status statement in that file.",
              "", "WHAT YOU MAY WRITE"]
    if thread.get("role") == "development":
        br = thread.get("branch") or branch_for(thread)
        # MEASURED 2026-10-01: a session started with an outcome branch still came up checked out on main, so the
        # platform does not create or switch the branch. The brief has to say how, and what to branch from.
        make = (f"Create it yourself before you write anything: git fetch origin {base} && git checkout -b {br} origin/{base}."
                if base else "You start on the default branch. Before you write anything, ask the Backlog thread which base branch to create it from.")
        lines += [f"- Only the branch {br}. {make} Never push to another branch and never merge. The development thread that owns release merges your work.",
                  "- Build only the lane below. A file that is not in your lane belongs to another thread; if you must touch one, stop and say so first."]
    else:
        lines.append("- Nothing in the repository until you are asked. Read, and report.")
    lines += ["", "YOUR LANE"]
    if lane_items:
        for it in lane_items:
            lines.append(f"- {it['ref']} ({it.get('minutes', '?')}m priced): {it.get('task', '')}")
    else:
        lines.append("- none assigned yet. Do not start any work.")
    bsid = backlog_session(threads)
    wake = None
    if thread.get("role") != "backlog":
        who = f"Backlog ({bsid})" if bsid else "Backlog (ask the owner for its session id)"
        wake = (f"- WAKE {who} whenever you finish something, start something, are blocked, or have a task you cannot solve inside the current release. "
                "Backlog's hourly check pauses itself when nothing is changing, and this is what restarts it. Say what changed in the message.")
    lines += ["", "HOW TO REPORT",
              "- Say what you did in your own thread. To reach another thread, create a Routine with no schedule bound to its session id, fire it once, then delete it; nothing comes back on that channel, so record replies in the repository.",
              "- Measured or marked: state only what a command produced in this session, and mark the rest TBC, re-verify. Never invent a name, date or figure."]
    if wake:
        lines.insert(len(lines) - 1, wake)
    lines += ["", "YOUR FIRST TASK"]
    lines.append(first_task or "Read CLAUDE.md, the board and docs/BACKLOG.md. Do not change any file and do not push. Reply in your own thread with three things only: your role and relationships as you understand them, the lane you would take and why, and any question that blocks you. Then wait.")
    return "\n".join(lines)


def session_request(thread, threads, links, lane_items, project, board_url, repo, environment_id=None, first_task=None, base=None):
    """The arguments for the session tool. A development thread is given its own branch; other roles are given none."""
    req = {
        "title": f"{thread['name']} ({project})",
        "prompt": brief(thread, threads, links, lane_items, project, board_url, repo, first_task, base),
        "source_url": repo,
        "tags": [f"backlog-thread:{slug(thread['name'])}"],
    }
    if thread.get("role") == "development":
        req["outcome_branch"] = thread.get("branch") or branch_for(thread)
    if environment_id:
        req["environment_id"] = environment_id
    return req
