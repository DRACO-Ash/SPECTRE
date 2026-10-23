"""Parse slice outputs, verify finding quotes against the tree. Usage: merge.py <repo> <slicedir> <outjson>"""
import re, sys, os, json, glob
repo, sd, outj = sys.argv[1:4]
FIELDS = ["ID","Lens","Severity","Confidence","Epistemics","Location","Evidence","Issue","Impact","Fix","Gate","Negative-check"]
def norm(s): return re.sub(r"\s+", " ", s.strip().strip("`").replace("’","'")).strip()
res = {"ledger": [], "claims": [], "findings": []}
for f in sorted(glob.glob(os.path.join(sd, "S*.md"))):
    sid = os.path.basename(f)[:3]; txt = open(f, encoding="utf-8").read()
    secs = re.split(r"^## ([A-D])\. .*$", txt, flags=re.M)
    sec = {secs[i]: secs[i+1] for i in range(1, len(secs)-1, 2)}
    for l in sec.get("A","").splitlines():
        m = re.match(r"\|\s*`?([^|`]+?)`?\s*\|\s*(REVIEWED|CLEAN|EXCLUDED)\s*\|\s*(.*?)\s*\|\s*$", l)
        if m: res["ledger"].append({"slice": sid, "path": m.group(1).strip(), "status": m.group(2), "reason": m.group(3)})
    for l in sec.get("B","").splitlines():
        cells = [c.strip() for c in l.strip().strip("|").split("|")]
        if len(cells) >= 6 and re.match(r"^\d+$", cells[0]):
            st = cells[-1].strip("* ")
            res["claims"].append({"slice": sid, "n": cells[0], "claim": cells[1], "source": cells[2], "impl": cells[3], "test": cells[4], "status": st})
    blocks = re.split(r"(?m)^\s*ID:\s*", sec.get("C",""))[1:]
    for b in blocks:
        d = {"slice": sid}; cur = "ID"; buf = {"ID": []}
        for line in ("ID: " + b).splitlines():
            m = re.match(r"^\s*(%s):\s*(.*)$" % "|".join(re.escape(x) for x in FIELDS), line)
            if m: cur = m.group(1); buf[cur] = [m.group(2)] if m.group(2) else []
            elif cur: buf.setdefault(cur, []).append(line)
        for k, v in buf.items():
            d[k] = "\n".join(v).strip() if k == "Evidence" else norm(" ".join(v))
        d["ID"] = d["ID"].split()[0] if d.get("ID") else "?"
        # quote verification
        loc = d.get("Location","")
        ev = [x.rstrip() for x in d.get("Evidence","").splitlines() if x.strip() and not x.strip().startswith("```")]
        locs = []; last = None
        for mm in re.finditer(r"(?:([A-Za-z0-9_./-]*[A-Za-z0-9_-]+(?:\.[A-Za-z0-9]+)?):)?(\d+)(?:-(\d+))?", loc):
            path = mm.group(1) if mm.group(1) and not mm.group(1).isdigit() else last
            if not path: continue
            last = path; locs.append((path, int(mm.group(2)), int(mm.group(3) or mm.group(2))))
        verdict = "NO-LOCATION"
        if locs:
            win = []
            missing = [l for l in locs if not os.path.exists(os.path.join(repo, l[0]))]
            for path, a, z in locs:
                pp = os.path.join(repo, path)
                if os.path.exists(pp):
                    lines = open(pp, encoding="utf-8", errors="replace").read().splitlines()
                    win += [norm(x) for x in lines[max(0,a-4):z+3]]
            bad = [e for e in ev if norm(e) and not any(norm(e) in w or (len(norm(e))>12 and w and w in norm(e)) for w in win)]
            if missing and not win: verdict = "PATH-MISSING"
            else: verdict = "MATCH" if ev and not bad else ("NO-EVIDENCE" if not ev else "MISMATCH: " + bad[0][:80])
        d["quote_check"] = verdict
        res["findings"].append(d)
json.dump(res, open(outj, "w"), indent=1)
from collections import Counter
print("ledger", len(res["ledger"]), Counter(x["status"] for x in res["ledger"]))
print("claims", len(res["claims"]), Counter(x["status"].split()[0] if x["status"] else "BLANK" for x in res["claims"]))
print("findings", len(res["findings"]), Counter(x.get("Severity","?") for x in res["findings"]))
print("quote", Counter(x["quote_check"].split(":")[0] for x in res["findings"]))
for x in res["findings"]:
    if x["quote_check"] != "MATCH": print(" ", x["ID"], x.get("Location"), "->", x["quote_check"])
