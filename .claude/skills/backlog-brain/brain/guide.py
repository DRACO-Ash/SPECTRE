"""The "how to use me" guide. One source file, assets/how-to-use.json, feeds the board page and this command.

Keeping one source is the point: a guide written twice goes out of step with itself, and a guide that names a button
that no longer exists is worse than none. The tests read the same file and check it against the page.
"""
import json
import os

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "how-to-use.json")
AUDIENCES = ("board", "pack")


def load_guide(path=None):
    with open(path or PATH, encoding="utf-8") as f:
        return json.load(f)


def render_text(guide, audience="pack", settings=None):
    """The guide as plain text for a terminal: a title, an intro, then each job with numbered steps. The board's tokens are
    filled from a board settings document (brain.board), or from what the page draws with none."""
    from .board import fill_guide
    if audience not in AUDIENCES:
        raise ValueError(f"audience must be one of {', '.join(AUDIENCES)}")
    g = fill_guide(guide[audience], settings)
    out = [g["title"], "", g["intro"]]
    if g.get("who"):
        out += [""] + [f"\u25cf {w}" for w in g["who"]]
    for job in g["jobs"]:
        out += ["", job["title"]]
        out += [f"  {n}. {s}" for n, s in enumerate(job["steps"], 1)]
    return "\n".join(out)
