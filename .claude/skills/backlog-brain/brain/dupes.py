"""Duplicate and overlap check for the backlog (VH-377, part 1): find open tasks that read like the same job.

A word-similarity scan, not a judgement: each task is its title and the first 120 characters of its note, every word
weighted by how rare it is across the open tasks, the title counting three times (so shared jargon counts for little), compared by cosine. The owner's
worry, 2026-10-03, was wasted time and corrupted engineered decisions from going over ground already covered, so:
  - a pair that belongs to one family (same parent, or refs on one numbered series such as VH-366-A and VH-366-B) is a
    split, not a duplicate, and is skipped;
  - a pair where either note already names the other's ref is a recorded relationship (superseded, folded, follows),
    and is skipped, because that is the record this check exists to encourage;
  - done and removed tasks are not compared.
It reports candidates for a person to look at. It never merges or removes anything. Standard library only.
"""
import math
import re

DONE = ("built", "closed", "released", "done", "removed")
STOP = set("the and for with that this from are was were has have had not but its into out new all any can will when then than "
           "also only each one two per via use used using over under after before about their there which what who how more most "
           "such may must should would could item task note see".split())
WORD = re.compile(r"[a-z][a-z0-9_]{2,}")


def _text(doc):
    # The title counts three times and the note's first 120 characters once: a note's opening is often a template ("Raised by
    # delivery in its report ...") that two unrelated tasks share, and the title says what the job is.
    t = doc.get("task") or ""
    return (" ".join([t, t, t]) + " " + (doc.get("note") or "")[:120]).lower()


def _words(doc):
    return [w for w in WORD.findall(_text(doc)) if w not in STOP]


def _declared(doc, other):
    """A pair a person has already judged: `distinctFrom` (not the same job) or `relatesTo` (related on purpose) names the other
    ref, as a list, a single ref or refs separated by commas, in any case. The guard then stops asking, which is how a pair found once is dismissed once."""
    want = str(other).strip().upper()
    for key in ("distinctFrom", "relatesTo"):
        v = doc.get(key)
        refs = v if isinstance(v, list) else str(v).split(",") if isinstance(v, str) else []
        if want in {str(r).strip().upper() for r in refs}:
            return True
    return False


def family(ref):
    """The numbered series a ref belongs to: VH-366-A and VH-366-B are VH-366, VH-009-Q1 is VH-009."""
    m = re.match(r"^([A-Za-z]+-\d+)", ref)
    return m.group(1) if m else ref


def find(items, threshold=0.55, top=20):
    """items: {ref: doc}. Returns [(score, ref_a, ref_b)], best first, at most `top`."""
    live = {r: d for r, d in items.items() if d.get("state") not in DONE}
    words = {r: _words(d) for r, d in live.items()}
    n = len(live)
    df = {}
    for ws in words.values():
        for w in set(ws):
            df[w] = df.get(w, 0) + 1
    vec = {}
    for r, ws in words.items():
        tf = {}
        for w in ws:
            tf[w] = tf.get(w, 0) + 1
        v = {w: c * math.log((n + 1) / (df[w] + 0.5)) for w, c in tf.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        vec[r] = {w: x / norm for w, x in v.items()}
    refs = sorted(live)
    out = []
    for i, a in enumerate(refs):
        for b in refs[i + 1:]:
            if family(a) == family(b) or live[a].get("parent") == live[b].get("parent") and live[a].get("parent"):
                continue
            if b in (live[a].get("note") or "") or a in (live[b].get("note") or ""):
                continue
            if _declared(live[a], b) or _declared(live[b], a):
                continue
            small, big = (vec[a], vec[b]) if len(vec[a]) <= len(vec[b]) else (vec[b], vec[a])
            s = sum(x * big.get(w, 0.0) for w, x in small.items())
            if s >= threshold:
                out.append((round(s, 3), a, b))
    return sorted(out, key=lambda t: (-t[0], t[1], t[2]))[:top]
