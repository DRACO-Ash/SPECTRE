"""Builds the one board write that puts a decision or a screenshot approval in front of the owner.

The Approvals panel in Backlog Brain shows every item whose state is "input" and which carries a `decision`.
A screenshot approval is the same item with `decision.images`, each naming an asset uploaded to the board.

  1. Upload each screenshot: Artifact tool, action "publish", url = the board, asset true, file_paths = [...].
     The result gives each file's 32 character id.
  2. Run `python3 scripts/brain.py approval ...` (or this project's `.claude/board/raise_approval.py`). It prints the JSON for ArtifactData action "update" on collection "items", doc_id = the ref.
     Pin it with if_version, the item's current version, as the tool requires for an existing document.

  brain.py approval --question "Approve the sign-in door?" --context "Rendered at 1280 x 900, tablet and phone." \\
      --image 0123...:"Desktop view":"Desktop 1280 x 900" --image ... \\
      --option "Approve as drawn|Development 2 builds it.|rec" --option "Changes needed|Say what to change."

Options are label|detail|rec; at most one is marked rec. The owner always gets a "Changes needed" (screenshot) or
"Something else" (decision) button as well, so do not add one unless you want different wording.
"""
import argparse
import json
import re
import sys

ID = re.compile(r"^[0-9a-f]{32}$")


def build(question, context, images, options, kind=None):
    question, context = " ".join(str(question).split()), " ".join(str(context or "").split())
    if not question:
        raise ValueError("a question is needed")
    if not 1 <= len(options) <= 4:
        raise ValueError("give one to four options")
    if len(images) > 8:
        raise ValueError("at most eight screenshots")
    imgs = []
    for im in images:
        if not ID.match(im["id"]):
            raise ValueError(f"image id must be 32 hex characters: {im['id'][:40]!r}")
        imgs.append({"id": im["id"], "alt": " ".join(im.get("alt", "").split())[:160], "caption": " ".join(im.get("caption", "").split())[:80]})
    opts = []
    for o in options:
        label = " ".join(o["label"].split())
        if not label:
            raise ValueError("an option needs a label")
        opts.append({k: v for k, v in (("label", label[:60]), ("detail", " ".join(o.get("detail", "").split())[:160]), ("recommended", True if o.get("recommended") else None)) if v})
    if sum(1 for o in opts if o.get("recommended")) > 1:
        raise ValueError("mark at most one option as recommended")
    decision = {"question": question[:200], "options": opts}
    if context:
        decision["context"] = context[:500]
    if imgs:
        decision["images"] = imgs
    if kind or imgs:
        decision["kind"] = kind or "screenshot"
    return {"state": "input", "decision": decision, "decisionAnswer": None}


def _opt(s):
    parts = (s.split("|") + ["", ""])[:3]
    return {"label": parts[0], "detail": parts[1], "recommended": parts[2].strip().lower() == "rec"}


def _img(s):
    parts = (s.split(":", 2) + ["", ""])[:3]
    return {"id": parts[0], "alt": parts[1], "caption": parts[2]}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="brain.py approval", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--question", required=True)
    ap.add_argument("--context", default="")
    ap.add_argument("--image", action="append", default=[], help="id:alt:caption")
    ap.add_argument("--option", action="append", required=True, help="label|detail|rec")
    ap.add_argument("--kind", choices=["screenshot", "decision"])
    a = ap.parse_args(argv)
    try:
        out = build(a.question, a.context, [_img(i) for i in a.image], [_opt(o) for o in a.option], a.kind)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0

