"""Evidence check for the backlog (VH-377, part 4): an open task that cites a file the repository does not have.

The owner asked that the backlog not send anyone over ground already covered or aimed at code that has gone. The cheapest
real signal is a path: a note that names `src/old/module.js` when that file is no longer in the tree is stale, or was never
right. This lists them. It never edits a task. A path is skipped when the words just before it say the file is meant to be
new (create, add, new, planned, will) or already gone (retired, removed, deleted, does not exist), and when it holds a
wildcard or a placeholder. Standard library only.
"""
import os
import re

OPEN = ("open", "allocated", "needscheck", "decision", "input", "answered", "inbuild", "queued", "held", "blocked", "needscost")
ROOTS = ("src", "public", "scripts", "test", "tests", "docs", "e2e", "db", "schema", ".claude", "migrations")
PATH = re.compile(r"(?<![\w/.-])((?:" + "|".join(re.escape(r) for r in ROOTS) + r")/[\w@./-]+\.[A-Za-z]{1,5})(?::\d+(?:-\d+)?)?(?![\w/*<>{-])")
NEW = re.compile(r"\b(creat\w*|add\w*|new|planned|will|introduc\w*|write|written|builds?|make|makes)\b", re.I)
GONE = re.compile(r"\b(retir\w*|remov\w*|delet\w*|dropp\w*|does not exist|no longer|never existed|not exist|missing|stale)\b", re.I)


def cited(doc):
    text = (doc.get("task") or "") + " \n" + (doc.get("note") or "")
    out = []
    for m in PATH.finditer(text):
        # PATH itself keeps out a wildcard or a placeholder (neither * nor < is in its character set, and a match may not end
        # just before one, so `test/route.test*.js` is not cut short) and trailing punctuation (a match ends on the letters of an
        # extension). VH-377's mutation run found the two checks that repeated this unreachable, and its review found the cut.
        p = m.group(1)
        before = text[max(0, m.start() - 70):m.start()]
        after = text[m.end():m.end() + 40]
        if NEW.search(before) or GONE.search(before) or GONE.search(after):
            continue
        out.append(p)
    return out


def missing(items, repo, trees=()):
    """[(ref, path)] for every open task citing a path that is under none of the given trees. repo is a folder or a list of folders;
    trees is a list of path sets read from git branches (git_trees), so a branch counts without being checked out."""
    repos = [repo] if isinstance(repo, str) else list(repo)
    out = []
    for ref, d in sorted(items.items()):
        if d.get("state") not in OPEN:
            continue
        seen = set()
        for p in cited(d):
            if p in seen:
                continue
            seen.add(p)
            if not any(os.path.exists(os.path.join(r, p)) for r in repos) and not any(p in t for t in trees):
                out.append((ref, p))
    return out


def git_trees(repo, patterns=("refs/remotes/origin/",)):
    """What counts as present when a task cites a path, read from git with nothing checked out (VH-377, revised after its review).
    HEAD counts whole. Every other fetched branch under `patterns` (a ref prefix or a list of them; the settings record's
    `guard.evidence_refs`) counts only for the paths it ADDED since it left HEAD's history, `git diff HEAD...ref`, so a merged or
    long-dead branch cannot keep a deleted file alive while work on an unmerged branch still counts. Returns a dict: `trees`,
    [(ref, set of paths)], HEAD first; `top`, the repository's top folder, whose working tree the caller also counts so a file not
    yet committed is not called stale; and `unread`, the refs that could not be read, which the caller reports rather than guesses.
    Paths are read NUL-separated as bytes, so a name git would quote reads as itself. Not a repository, git missing, or no commit
    yet gives no trees."""
    import subprocess
    out = {"trees": [], "top": None, "unread": []}
    pats = [patterns] if isinstance(patterns, str) else list(patterns)
    def git(*a):
        return subprocess.run(["git", "-C", repo, *a], capture_output=True, timeout=60)
    def names(raw):
        return {p for p in os.fsdecode(raw).split("\0") if p}
    try:
        top = git("rev-parse", "--show-toplevel")
        if top.returncode != 0:
            return out
        head = git("ls-tree", "-r", "-z", "--full-tree", "--name-only", "HEAD")
        refs = [r for r in os.fsdecode(git("for-each-ref", "--format=%(refname)", *pats).stdout).split() if not r.endswith("/HEAD")]
    except (OSError, subprocess.SubprocessError):
        return out
    if head.returncode != 0:
        return out
    out["top"] = os.fsdecode(top.stdout).strip()
    out["trees"].append(("HEAD", names(head.stdout)))
    for r in refs:
        try:
            d = git("diff", "--name-only", "-z", "--no-renames", "--diff-filter=A", "HEAD..." + r)
        except (OSError, subprocess.SubprocessError):
            d = None
        if d is None or d.returncode != 0:
            out["unread"].append(r)
        else:
            out["trees"].append((r, names(d.stdout)))
    return out
