"""Build REMEDIATION.md. Usage: remed.py <scratch> <repo>"""
import json, sys, re, collections
S, R = sys.argv[1:3]
c = json.load(open(S + "/combined.json")); idmap = json.load(open(S + "/idmap.json"))
conf = [f for f in c if f["ID"] in idmap]; conf.sort(key=lambda f: idmap[f["ID"]])
def files(f):
    fs = []; last = None
    for mm in re.finditer(r"(?:([A-Za-z0-9_./-]*[A-Za-z0-9_-]+(?:\.[A-Za-z0-9]+)?):)?(\d+)(?:-(\d+))?", f.get("Location", "")):
        p = mm.group(1) if mm.group(1) and not mm.group(1).isdigit() else last
        if p: last = p; fs.append(p)
    return fs
def effort(f):
    fs = files(f); n = len(fs); u = len(set(fs))
    if f["Lens"].startswith(("L7", "L6")) or u >= 3 or n > 4: return "L"
    if u == 2 or n > 1: return "M"
    return "S"
def blast(f):
    u = sorted(set(files(f)))
    area = set()
    for p in u:
        if p.startswith("spectre/astro"): area.add("astro solvers")
        elif p.startswith("spectre/domain"): area.add("domain")
        elif p.startswith("spectre/web/templates"): area.add("operator UI")
        elif p.startswith("spectre/web"): area.add("web routes")
        elif p.startswith("tests/"): area.add("tests only")
        elif p.startswith(("README", "docs/", "SECURITY", "READINESS")): area.add("documentation")
        else: area.add("build/CI/config")
    return f"{len(u)} file(s): " + ", ".join(sorted(area))
def esc(s): return (s or "").replace("|", "/").replace("\n", " ")
blk = [f for f in conf if f["v"]["sev"] == "Blocker"]
quick = [f for f in conf if f["v"]["sev"] in ("High", "Medium") and effort(f) == "S"]
struct = [f for f in conf if f not in blk and f not in quick]
with open(R + "/audit/REMEDIATION.md", "w") as o:
    o.write("# SPECTRE audit: remediation plan (phase 8.2 and 8.3)\n\n")
    o.write(f"One row per confirmed finding ({len(conf)}). Fix and Gate come from the finding (`audit/FINDINGS.md`). Every row carries a regression gate: the test, lint rule, type constraint or CI check that would fail if the defect returned.\n\n")
    o.write("**Effort and blast radius are estimates (inference), derived mechanically:**\n● S: one location in one file.\n● M: two files, or several locations in one.\n● L: three or more files, more than four locations, or a design, structure or complexity lens.\nBlast radius counts the distinct files cited and the areas they sit in. Treat both as a sizing aid, not a commitment.\n\n")
    o.write("""## Sequence

1. **Blockers first**, before the console is used for any decision. Each is either an exploitable security flaw or a numerically incorrect output presented as computed.
2. **Unblock the gates.** Make CI execute (F-S00-01 and F-S00-08 together), so every later fix lands behind real lint, type and test jobs. This is the cheapest high-value change in the repository.
3. **Quick wins:** High and Medium findings with a single-location fix (effort S).
4. **Structural:** everything else, grouped by the root-cause clusters below so one change closes several findings.

## Root-cause clusters (inference, from reading the confirmed set together)

| Cluster | Findings it closes (origin IDs) | One change |
|---|---|---|
| Identity keyed on username, not user id | F-S08-02, F-S08-03, F-S08-08, F-S07-01 | Key the session token, the SessionState store and revocation on the immutable user id. Clear SessionState on delete, password reset and session expiry. Hold UDL credentials per browser session, not per username. |
| Heuristic scores presented as computed physics | F-S02-07, F-S02-08, F-S02-09, F-S02-10, F-S02-11, F-S02-12, F-S05-02, F-S05-09, F-S04-05, F-S06-07 | A `modelled: bool` and `basis: str` on every score type, carried through the payload. A shared template macro that renders a "modelled estimate, not a computed solution" badge wherever a modelled value appears. The agreed July remediation, never implemented. |
| Unit and frame errors at function boundaries | F-S01-01, F-S06-01, F-S06-02, F-S04-03, F-S02-04, F-S10-03 | Typed unit wrappers (NewType for km, m/s, days, deg) at the public solver boundary, and a lint that flags `degrees(` on values already in degrees. |
| Solvers exercised but not pinned | F-S01-21, F-S00-02, F-S00-03, F-S00-04, F-S00-05, F-S00-14 | One reference-case test per solver (Curtis and Vallado worked examples, with stated tolerance), plus a CI mutation sample on `astro/` and the security core. |
| Gates that never run | F-S00-01, F-S00-08, F-S00-10, F-S00-12 | Install locked sets in CI, select BLE and RUF100, keep one coverage floor. |

""")
    def table(title, rows):
        o.write(f"## {title} ({len(rows)})\n\n| Final ID | Origin | Severity | Effort | Blast radius | Fix | Regression gate |\n|---|---|---|---|---|---|---|\n")
        for f in rows: o.write(f"| {idmap[f['ID']]} | {f['ID']} | {f['v']['sev']} | {effort(f)} | {blast(f)} | {esc(f.get('Fix'))} | {esc(f.get('Gate'))} |\n")
        o.write("\n")
    table("Step 1: Blockers", blk); table("Step 3: Quick wins (High and Medium, effort S)", quick); table("Step 4: Structural and remaining", struct)
    missing = [f["ID"] for f in conf if not (f.get("Gate") or "").strip()]
    o.write(f"\nGate completeness check: {len(conf)-len(missing)} of {len(conf)} findings carry a non-empty gate." + (f" Missing: {missing}." if missing else "") + "\n")
print(len(blk), len(quick), len(struct))
