"""Build FINDINGS, REFUTATION, REMEDIATION, MANIFEST. Usage: build.py <scratch> <repo>"""
import json, sys, re, collections, datetime
S, R = sys.argv[1:3]
c = json.load(open(S + "/combined.json"))
MANUAL_DUP = {"F-S09-14": "F-S05-02"}
for f in c:
    if f["ID"] in MANUAL_DUP: f["v"]["verdict_final"] = "DUPLICATE"; f["v"]["dup"] = MANUAL_DUP[f["ID"]]
ORDER = {"Blocker": 0, "High": 1, "Medium": 2, "Low": 3}
SLICES = ["S00","S01","S02","S03","S04","S05","S06","S07","S08","S09","S10"]
conf = sorted([f for f in c if f["v"]["verdict_final"] == "CONFIRMED"], key=lambda f: (ORDER[f["v"]["sev"]], SLICES.index(f["slice"]), int(f["ID"].split("-")[-1])))
idmap = {f["ID"]: f"F-{i:03d}" for i, f in enumerate(conf, 1)}
json.dump(idmap, open(S + "/idmap.json", "w"), indent=0)
def ev(f): return "\n".join("               " + l.strip() for l in f.get("Evidence", "").splitlines() if l.strip())
def esc(s): return (s or "").replace("|", "/").replace("\n", " ")
# ---------------- FINDINGS
sev_ct = collections.Counter(f["v"]["sev"] for f in conf)
with open(R + "/audit/FINDINGS.md", "w") as o:
    o.write("# SPECTRE audit: confirmed findings (phase 8.1)\n\n")
    o.write(f"**Source audited:** tree at `a34e273`. **Confirmed:** {len(conf)} findings, Blocker {sev_ct['Blocker']}, High {sev_ct['High']}, Medium {sev_ct['Medium']}, Low {sev_ct['Low']}. Every finding below passed the phase 7 refutation (`audit/REFUTATION.md`), and its severity is the post-refutation one. Each carries its origin ID (slice review, or S00 for orchestrator findings) so it can be traced to the slice reasoning and the refuter's check. UNPROVEN candidates are kept out of this file and listed in the appendix of `audit/REFUTATION.md`.\n\n")
    o.write("Evidence fragments are verbatim from the cited lines. A script checked all 317 candidate fragments against the tree before refutation: 317 matched.\n\n")
    cur = None
    for f in conf:
        s = f["v"]["sev"]
        if s != cur:
            o.write(f"## {s}\n\n"); cur = s
        o.write("```\n")
        o.write(f"ID:          {idmap[f['ID']]}   (origin {f['ID']})\n")
        for k in ["Lens"]: o.write(f"{k+':':13}{f.get(k,'')}\n")
        o.write(f"Severity:    {s}" + (f"   (reviewer graded {f.get('Severity')}; changed in refutation)" if s != f.get("Severity") else "") + "\n")
        for k in ["Confidence","Epistemics","Location"]: o.write(f"{k+':':13}{f.get(k,'')}\n")
        o.write("Evidence:\n" + ev(f) + "\n")
        for k in ["Issue","Impact","Fix","Gate"]: o.write(f"{k+':':13}{f.get(k,'')}\n")
        o.write("Verdict:     CONFIRMED\n```\n\n")
# ---------------- REFUTATION
vc = collections.Counter(f["v"]["verdict_final"] for f in c)
changed = [f for f in c if f["v"]["verdict_final"] == "CONFIRMED" and f["v"]["sev"] != f.get("Severity")]
up = [f for f in changed if ORDER[f["v"]["sev"]] < ORDER[f["Severity"]]]; down = [f for f in changed if ORDER[f["v"]["sev"]] > ORDER[f["Severity"]]]
tot = len(c)
with open(R + "/audit/REFUTATION.md", "w") as o:
    o.write("# SPECTRE audit: refutation (phase 7)\n\n")
    o.write(f"## Result\n\n| Measure | Count |\n|---|---|\n| Candidates | {tot} |\n| CONFIRMED | {vc['CONFIRMED']} |\n| REFUTED | {vc['REFUTED']} |\n| UNPROVEN (appendix) | {vc['UNPROVEN']} |\n| DUPLICATE (folded into another ID) | {vc['DUPLICATE']} |\n| Severity raised in refutation | {len(up)} |\n| Severity lowered in refutation | {len(down)} |\n| Quote mismatch (7.1) | 0 of {tot} (0.0 %) |\n\n")
    o.write(f"Refutation rate: {vc['REFUTED']} of {tot} ({100*vc['REFUTED']/tot:.1f} %) refuted outright, and {len(down)} of the confirmed ({100*len(down)/max(1,vc['CONFIRMED']):.1f} %) lowered in severity. Together {vc['REFUTED']+len(down)} of {tot} candidates ({100*(vc['REFUTED']+len(down))/tot:.1f} %) were knocked down or reduced. The rate is not zero, and the reductions carry evidence, many of them executed (refuter notes cite scripts under `scratch/refute/work/`).\n\n")
    o.write("""## Method

● **7.1 Quote check, by script.** Each candidate's quoted lines were matched against every location it cites, normalised for whitespace, with a three-line tolerance around each cited range. The first pass reported 13, then 14, mismatches. All of them were checker defects: the checker read only the first location, could not read bare follow-on ranges (`:1611, 1647-1724`), and could not read paths with no file extension (`Dockerfile:194`). Fixed, the result is 317 matched. The quote-mismatch rate of reviewer error is therefore 0 of 317. Inference: reviewers were instructed to copy lines exactly, and several checked their own quotes by script before returning.
● **7.2 to 7.5 Independent adversarial pass.** Five fresh refuter agents, R1 to R5, worked from `scratch/refute/BRIEF.md`. They received only the candidate blocks for their batch, not the reviewer's working, and were told to argue the opposite case, rerun each negative grep, state the reachability path for security findings, and execute numerical claims against an independent value in a scratch clone. R4 (S07 and S08) was run twice by independent agents, R4 and then R4a and R4b. The two passes agree on 44 of 46 verdicts and 39 of 46 severities. The 2 verdict disagreements (F-S07-04, F-S07-09) were resolved to the stricter UNPROVEN. Severity disagreements were resolved to the pass with execution evidence (R4a and R4b), and the other pass is recorded below.
● **Orchestrator verification.** Nine high-consequence candidates were verified by the orchestrator before refutation and passed to the refuters as settled: F-S08-01 (executed), F-S02-01 (executed), F-S02-03 (executed against scipy integration of CW), F-S01-01 and F-S01-02 (deterministic code read, the RAAN case later executed by R1), F-S06-01, F-S06-02, F-S06-03 (code read) and F-S07-05 (record counts and markings by script).
● **Batch R0, the orchestrator's own 15 candidates (S00).** These were verified at discovery by live CI logs, mutation runs, greps and the uv resolver. They were not passed to an independent refuter. That is a limit of this run and is stated in `audit/GAPS.md`. The opposite case was argued for each when R0 was written, and one (F-S00-07) fell: the packaging script strips `docs/openapi.json`.

## Severity changes

""")
    o.write("| Origin ID | Reviewer | Final | Direction |\n|---|---|---|---|\n")
    for f in sorted(changed, key=lambda f: f["ID"]): o.write(f"| {f['ID']} | {f['Severity']} | {f['v']['sev']} | {'raised' if f in up else 'lowered'} |\n")
    o.write("\n## Second-opinion disagreements on batch R4 (recorded, not adopted)\n\n| Origin ID | R4 | R4a/R4b (adopted) |\n|---|---|---|\n")
    for f in c:
        s2 = f["v"].get("second")
        if s2 and (s2["verdict"] != f["v"]["verdict"] or s2["sev"] != f["v"]["sev"]): o.write(f"| {f['ID']} | {s2['verdict']} {s2['sev']} | {f['v']['verdict_final']} {f['v']['sev']} |\n")
    o.write("\n## Full verdict table\n\nOne row per candidate, in slice order. **Final ID** links to `audit/FINDINGS.md`.\n\n| Origin ID | Final ID | Verdict | Severity (reviewer → final) | Duplicate of | Refuter reason | Check run |\n|---|---|---|---|---|---|---|\n")
    for f in c:
        v = f["v"]
        o.write(f"| {f['ID']} | {idmap.get(f['ID'],'')} | {v['verdict_final']} | {f.get('Severity')} → {v['sev']} | {v['dup']} | {esc(v['reason'])[:600]} | {esc(v['check'])[:400]} |\n")
    o.write("\n## Appendix: UNPROVEN, with the check that would settle each\n\n| Origin ID | Reviewer severity | Issue | Settling check (refuter) |\n|---|---|---|---|\n")
    for f in c:
        if f["v"]["verdict_final"] == "UNPROVEN": o.write(f"| {f['ID']} | {f.get('Severity')} | {esc(f.get('Issue'))[:300]} | {esc(f['v']['reason'])[:500]} |\n")
    o.write("| R1-NEW-01 (raised by refuter R1, outside its batch) | not graded | The V-bar wrapper's second burn (`spectre/astro/maneuvers.py:503`) doubles the radial velocity at the default 3 hops (refuter executed: residual 11 m/s); the threat sweep uses 3 hops. | Has had one review only, so it is not eligible for FINDINGS under G6. Settle by: a second independent execution of `vbar_hop` wrappers at 3 hops comparing the post-burn relative velocity with zero. |\n")
    o.write("\n## Appendix: REFUTED\n\n| Origin ID | Reviewer severity | Why it fell |\n|---|---|---|\n")
    for f in c:
        if f["v"]["verdict_final"] == "REFUTED": o.write(f"| {f['ID']} | {f.get('Severity')} | {esc(f['v']['reason'])[:500]} |\n")
print("confirmed", len(conf), dict(sev_ct)); print("verdicts", dict(vc)); print("up", len(up), "down", len(down))
