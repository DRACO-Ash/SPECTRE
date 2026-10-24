"""Classify suppression sites. Usage: supp.py <repo> <grep-output> <out-md>"""
import re, sys, os, collections
repo, src, out = sys.argv[1:4]
SELECTED = ("E", "F", "I", "UP", "B", "SIM")   # pyproject.toml [tool.ruff.lint] select
IGNORED = {"B008", "E501", "SIM108"}
KINDS = [("noqa", r"#\s*noqa(?::\s*([A-Z0-9, ]+))?"), ("type-ignore", r"#\s*type:\s*ignore(\[[^\]]*\])?"),
         ("nosec", r"#\s*nosec\b(\s+B\d+)?"), ("pyright-ignore", r"pyright:\s*ignore"), ("no-cover", r"pragma:\s*no ?cover"),
         ("NOSONAR", r"NOSONAR"), ("skip", r"@pytest\.mark\.(skip|skipif|xfail)|pytest\.skip\(|pytest\.importorskip|unittest\.skip"),
         ("filterwarnings", r"filterwarnings")]
rows = []; tally = collections.Counter(); area = collections.Counter(); inert = []
for line in open(src):
    path, ln, text = line.rstrip("\n").split(":", 2)
    if path.endswith((".toml", ".properties", ".cfg")): kind_hits = [("config", None)]
    else: kind_hits = [(k, re.search(p, text)) for k, p in KINDS if re.search(p, text)]
    if not kind_hits: kind_hits = [("other", None)]
    lines = open(os.path.join(repo, path), encoding="utf-8", errors="replace").read().splitlines()
    i = int(ln) - 1
    for kind, m in kind_hits:
        tail = text[m.end():].strip() if m else ""
        tail = re.sub(r"^[-:–\s]+", "", tail)
        prev = lines[i - 1].strip() if i > 0 else ""
        if kind == "skip" and re.search(r"reason\s*=", text): just = "inline reason="
        elif tail and not tail.startswith("#") and len(tail) > 3: just = "inline: " + tail[:70]
        elif prev.startswith("#"): just = "comment above: " + prev[1:].strip()[:60]
        else: just = "NONE"
        note = ""
        if kind == "noqa" and m and m.group(1):
            codes = [c.strip() for c in m.group(1).split(",") if c.strip()]
            dead = [c for c in codes if re.match(r"[A-Z]+", c).group() not in SELECTED or c in IGNORED]
            if dead: note = "suppresses rule(s) not enabled: " + ",".join(dead); inert.append((path, ln, ",".join(dead)))
        top = path.split("/")[0] if "/" in path else "(root)"
        if path.startswith("tests/"): top = "tests"
        elif path.startswith("spectre/") or path.startswith("tle_clustering/"): top = "product"
        tally[kind] += 1; area[(top, kind)] += 1
        rows.append((path, ln, kind, just, note, text.strip()[:110].replace("|", "\\|")))
with open(out, "w") as f:
    f.write("| Path:line | Kind | Justification (heuristic) | Note | Fragment |\n|---|---|---|---|---|\n")
    for p, l, k, j, n, t in rows: f.write(f"| `{p}:{l}` | {k} | {j.replace('|','/')} | {n} | `{t}` |\n")
print("by kind:", dict(tally)); print("by area/kind:", dict(area))
print("unjustified:", sum(1 for r in rows if r[3] == "NONE"), "of", len(rows))
print("unjustified product:", sum(1 for r in rows if r[3] == "NONE" and not r[0].startswith(("tests/", "scripts/", "docs/"))))
print("inert noqa sites:", len(inert)); print(collections.Counter(c for _, _, c in inert).most_common(12))
