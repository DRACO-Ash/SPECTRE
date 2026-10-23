"""Combine candidates with refutation verdicts. Usage: combine.py <scratch>"""
import json, sys, re, collections
S = sys.argv[1]; m = json.load(open(S + "/merged.json"))
def load(files):
    r = {}
    for f in files:
        for l in open(f"{S}/refute/{f}"):
            if l.startswith("| F-"):
                c = [x.strip() for x in l.strip().strip("|").split("|")]
                while len(c) < 6: c.append("")
                sev = re.sub(r"\s*\(.*", "", c[2]).strip("* ") or ""
                dup = re.search(r"F-S\d\d-\d+", c[3]); 
                r[c[0]] = {"verdict": c[1].split()[0].strip("*"), "sev": sev, "dup": dup.group(0) if dup else "", "reason": c[4], "check": c[5], "raw_sev": c[2]}
    return r
prim = load(["R0.verdicts.md","R1.verdicts.md","R2.verdicts.md","R3.verdicts.md","R4a.verdicts.md","R4b.verdicts.md","R5.verdicts.md"])
second = load(["R4.verdicts.md"])
out = []; miss = []
for f in m["findings"]:
    v = prim.get(f["ID"])
    if not v: miss.append(f["ID"]); continue
    v = dict(v); v["second"] = second.get(f["ID"])
    if v["second"] and "UNPROVEN" in (v["verdict"], v["second"]["verdict"]): v["verdict"] = "UNPROVEN"
    if v["dup"] or "DUPLICATE" in v["verdict"]: v["verdict_final"] = "DUPLICATE"
    else: v["verdict_final"] = v["verdict"]
    if not v["sev"] or v["sev"] not in ("Blocker","High","Medium","Low"): v["sev"] = f.get("Severity")
    f.update({"v": v}); out.append(f)
json.dump(out, open(S + "/combined.json", "w"), indent=1)
print("missing verdicts", miss)
print("verdicts", collections.Counter(f["v"]["verdict_final"] for f in out))
conf = [f for f in out if f["v"]["verdict_final"] == "CONFIRMED"]
print("confirmed by severity", collections.Counter(f["v"]["sev"] for f in conf))
changed = [f for f in out if f["v"]["sev"] != f.get("Severity")]
print("severity changed", len(changed), collections.Counter((f.get("Severity"), f["v"]["sev"]) for f in changed))
# cross-slice duplicate candidates: same path, line ranges within 3 lines
def spans(f):
    r=[]; last=None
    for mm in re.finditer(r"(?:([A-Za-z0-9_./-]*[A-Za-z0-9_-]+(?:\.[A-Za-z0-9]+)?):)?(\d+)(?:-(\d+))?", f.get("Location","")):
        p = mm.group(1) if mm.group(1) and not mm.group(1).isdigit() else last
        if p: last=p; r.append((p,int(mm.group(2)),int(mm.group(3) or mm.group(2))))
    return r
pairs=[]
for i,a in enumerate(conf):
    for b in conf[i+1:]:
        if a["slice"]==b["slice"]: continue
        if any(x[0]==y[0] and x[1]<=y[2]+3 and y[1]<=x[2]+3 for x in spans(a)[:1] for y in spans(b)[:1]):
            pairs.append((a["ID"],b["ID"],spans(a)[0],a["Issue"][:70],b["Issue"][:70]))
print("cross-slice overlap pairs", len(pairs))
for p in pairs: print(" ",p[0],p[1],p[2][0],p[2][1],"|",p[3],"||",p[4])
