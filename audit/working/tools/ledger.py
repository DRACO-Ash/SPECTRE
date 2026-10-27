"""Build audit/LEDGER.md inventory table from git ls-files."""
import subprocess, sys, os, re
os.chdir(sys.argv[1])
files = subprocess.run(["git","ls-files","-s"],capture_output=True,text=True,check=True).stdout.splitlines()
LANG = {".py":"Python",".html":"HTML/Jinja2",".js":"JavaScript",".css":"CSS",".svg":"SVG",".md":"Markdown",
        ".yaml":"YAML",".yml":"YAML",".toml":"TOML",".json":"JSON",".txt":"Text",".in":"pip-compile input",
        ".sh":"Shell",".zip":"ZIP archive",".docx":"Word (binary)",".properties":"Properties"}
VENDORED = {"spectre/web/static/chart.umd.min.js":"Chart.js 4.4.7","spectre/web/static/chartjs-plugin-zoom.min.js":"chartjs-plugin-zoom 2.0.1",
            "spectre/web/static/hammer.min.js":"Hammer.JS 2.0.7","spectre/web/static/htmx.min.js":"htmx 1.9.12"}
MAINS = set(subprocess.run(["git","grep","-l","__name__ == .__main__.","--","*.py"],capture_output=True,text=True).stdout.split())
ROUTES = set(subprocess.run(["git","grep","-lE","@router\\.|@app\\.","--","spectre/*.py"],capture_output=True,text=True).stdout.split())
def role(p):
    base=os.path.basename(p); ext=os.path.splitext(p)[1]
    if p in VENDORED: return "vendored"
    if p.startswith("audit/") or p.startswith(".claude/"): return "audit-tooling"
    if p.startswith("tests/"): return "test" if ext==".py" else "test-fixture"
    if re.match(r"requirements(-\w+)?\.txt$",base): return "generated"
    if p=="docs/openapi.json": return "generated"
    if ext in (".svg",".zip",".docx",".pdf",".png") : return "asset"
    if p.startswith("spectre/web/static/") and ext in (".css",".html"): return "asset"
    if p.startswith("spectre/web/static/") and ext==".md": return "docs"
    if p.startswith("spectre/data/") and ext==".json": return "data"
    if ext==".md" or p.endswith(".txt"): return "docs"
    if p.startswith("spectre/web/templates/"): return "source"
    if ext in (".py",".sh") : return "source"
    if base.startswith(".") or ext in (".toml",".yaml",".yml",".in",".properties") or base in ("Dockerfile","Dockerfile.docker-only","CODEOWNERS"): return "config"
    if ext==".html": return "asset"
    return "TBC"
def entry(p):
    r=[]
    if p=="spectre/web/_entrypoint.py": r.append("container CMD / console script")
    if p=="spectre/web/app.py": r.append("ASGI app")
    if p in ROUTES and p!="spectre/web/app.py": r.append("HTTP routes")
    if p in MAINS and p!="spectre/web/_entrypoint.py": r.append("__main__ CLI")
    if p.endswith(".sh") and p.startswith("scripts/"): r.append("shell CLI")
    if p=="query_UDL_Data.py": r.append("top-level script (no __main__ guard)")
    if p==".github/workflows/ci.yml": r.append("CI pipeline")
    if p in ("Dockerfile","Dockerfile.docker-only"): r.append("image build")
    return "; ".join(r) or "no"
rows=[]; counts={}
for line in files:
    meta,p=line.split("\t",1); mode=meta.split()[0]
    if mode=="160000":
        rows.append((p,"gitlink","-","gitlink (orphan submodule)","no","EXCLUDED")); counts["gitlink (orphan submodule)"]=counts.get("gitlink (orphan submodule)",0)+1; continue
    ext=os.path.splitext(p)[1]; b=os.path.basename(p)
    lang=LANG.get(ext, "Dockerfile" if b.startswith("Dockerfile") else ("text" if b in ("CODEOWNERS",".gitignore",".dockerignore",".env.example") else "TBC"))
    try:
        data=open(p,"rb").read(); n=str(data.count(b"\n")) if b"\0" not in data[:8000] else "binary"
    except Exception as e: n="ERR"
    r=role(p); counts[r]=counts.get(r,0)+1
    status="EXCLUDED" if r in ("vendored","audit-tooling","generated") or ext in (".zip",".docx") else "PENDING"
    rows.append((p,lang,n,r,entry(p),status))
print(f"<!-- generated rows={len(rows)} -->")
for k,v in sorted(counts.items()): print(f"<!-- role {k}={v} -->")
print("| # | Path | Language | Lines | Role | Entry point | Status |")
print("|---|------|----------|-------|------|-------------|--------|")
for i,r in enumerate(rows,1): print(f"| {i} | `{r[0]}` | {r[1]} | {r[2]} | {r[3]} | {r[4]} | {r[5]} |")
