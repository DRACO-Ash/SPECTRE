"""Builds assets/example/items.json from a dump of the Vendor Fishing board (the worked example).

Gate profiles are classified by hand from the files each item touches (server, client, tooling, or mixed). An
item not classified keeps no gates field, which the model treats as every gate: fail closed.
Usage: make_example.py <items dump dir> <out file>
"""
import json, os, sys
OPEN = ("open", "allocated", "needscheck", "decision", "input", "answered")
TOOLING = set("VH-162 VH-210 VH-211 VH-133 VH-135 VH-184 VH-343 VH-147 VH-355 VH-354 VH-341 VH-075 VH-077 VH-070 VH-065 VH-019".split())
SERVER = set("VH-363 VH-363-B VH-364 VH-344 VH-358 VH-359 VH-359-B VH-360 VH-361 VH-362 VH-365 VH-179 VH-266 VH-346 VH-350 VH-351 VH-257 VH-178 VH-009-Q1 VH-009-Q2 VH-079 VH-080 VH-345".split())
CLIENT = set("VH-009-Q3 VH-139 VH-144 VH-069 VH-137 VH-202 VH-203 VH-204 VH-205 VH-322 VH-329 VH-330 VH-331 VH-333 VH-335 VH-225 VH-092 VH-206 VH-208 VH-306 VH-334 VH-337 VH-148 VH-342 VH-353 VH-338 VH-339 VH-340 VH-348 VH-352".split())
DEPS = {"VH-363-B": ["VH-363"], "VH-359-B": ["VH-359"], "VH-358": ["VH-344"], "VH-009-Q2": ["VH-079"], "VH-318-B": ["VH-318-A"],
        "VH-318-C": ["VH-318-B"], "VH-318-D": ["VH-318-C"], "VH-318-E": ["VH-318-C"], "VH-318-F": ["VH-318-D", "VH-318-E"],
        "VH-318-H": ["VH-318-D"], "VH-072": ["VH-318-F"], "VH-160": ["VH-318-F"]}
# Files, so the worked example exercises lanes (VH-471): items that touch the same file must share a lane.
FILES = {"VH-004": ["public/views/analytics.js"], "VH-007": ["public/views/analytics.js"], "VH-009-Q1": ["src/db/queue.js"],
         "VH-009-Q2": ["src/db/queue.js"], "VH-015": ["src/api.js"]}
LOCK_V28 = {"VH-318-A", "VH-318-B", "VH-318-C", "VH-318-D", "VH-318-E", "VH-318-F", "VH-318-G", "VH-318-H", "VH-318-I"}
src, out = sys.argv[1], sys.argv[2]
items = []
for f in sorted(os.listdir(src)):
    x = json.load(open(os.path.join(src, f))); d = x.get("data", x); ref = f[:-5]
    if d.get("state") not in OPEN or not d.get("minutes") or d.get("release") in ("r-closed",):
        continue
    it = {"ref": ref, "minutes": d["minutes"], "priority": d.get("priority"), "state": "open", "task": (d.get("task") or "")[:90]}
    if ref in ("VH-273", "VH-215"):
        it["kind"] = "research"
    if d.get("state") in ("input", "decision") and ref not in ("VH-366", "VH-366-D"):
        it["needs_owner"] = True
    if ref in SERVER: it["gates"] = ["eng", "sec"]
    elif ref in TOOLING: it["gates"] = ["eng"]
    elif ref in CLIENT: it["gates"] = ["sec", "design"]
    rel = d.get("release")
    group = ("storage" if ref in SERVER or ref in TOOLING else "polish" if ref in CLIENT or rel == "r-a11y" else "hugo" if rel == "r-v2-7" else "domain")
    it["group"] = group; it["order"] = {"storage": 1, "hugo": 2, "domain": 3, "polish": 4}[group]
    if ref.startswith("VH-366"): it["track"] = "tooling"
    if ref in DEPS: it["deps"] = DEPS[ref]
    if ref in FILES: it["files"] = FILES[ref]
    if ref in LOCK_V28: it["lock"] = "V2.8"
    items.append(it)
json.dump(items, open(out, "w"), indent=0)
print(len(items), "items,", sum(i["minutes"] for i in items), "priced minutes")
