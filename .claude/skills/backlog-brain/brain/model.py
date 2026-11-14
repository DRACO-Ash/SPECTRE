"""Settings and item model for the Backlog Brain.

Everything project-specific lives in one settings record (config.json). Nothing here knows about a particular
project. Loading fails closed: every problem is collected and reported together, and a record with any problem
is refused rather than half-applied.
"""
import fnmatch
import json
import re

SCHEMA = 1
PRIORITY_RANK = {"high": 0, "med": 1, "low": 2}
DONE_STATES = ("built", "closed", "released", "done")
OFF_PATH_KINDS = ("research", "investigation")
DEFAULTS = {
    "releases": {
        "naming": "V{major}.{minor}",
        "start": "V1.0",
        "floor_min": 720,      # a release is sized to at least this many minutes from build to upload
        "cap_min": 840,        # and at most this many
        "overhead_min": 0,     # measured per-release cost that is not build (gates, packaging, refusals)
        "pace": 1.0,           # wall-clock minutes per priced minute until the project has measured its own
        "gate_savings": True,  # a release that triggers fewer gates saves those gates' minutes of overhead
        "fill_to_floor": True,
    },
    "agents": {"max_concurrent": 1},
    "working": {"hours_per_day": 8, "days_per_week": 5},
    "gates": [],
    "people": [],
    "risk_paths": [],
}


class ConfigError(ValueError):
    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("; ".join(self.problems))


def _merge(base, extra):
    out = json.loads(json.dumps(base))
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(raw):
    """Validate a settings record (a dict). Returns the record with defaults applied, or raises ConfigError."""
    problems = []
    if not isinstance(raw, dict):
        raise ConfigError(["the settings record is not an object"])
    if raw.get("schema") != SCHEMA:
        problems.append(f"schema must be {SCHEMA}, found {raw.get('schema')!r}; run the upgrade before using this record")
    cfg = _merge(DEFAULTS, raw)
    proj = cfg.get("project") or {}
    if not proj.get("name"):
        problems.append("project.name is required")
    if not re.fullmatch(r"[A-Za-z0-9]+-?", str(proj.get("ref_prefix", ""))):
        problems.append("project.ref_prefix is required and must look like 'PRJ-'")
    r = cfg["releases"]
    for k in ("floor_min", "cap_min", "overhead_min", "pace"):
        if not isinstance(r.get(k), (int, float)) or isinstance(r.get(k), bool) or r[k] < 0:
            problems.append(f"releases.{k} must be a non-negative number")
    if isinstance(r.get("floor_min"), (int, float)) and isinstance(r.get("cap_min"), (int, float)) and r["floor_min"] > r["cap_min"]:
        problems.append("releases.floor_min is above releases.cap_min")
    if isinstance(r.get("pace"), (int, float)) and r["pace"] == 0:
        problems.append("releases.pace must be above zero")
    if not re.search(r"\{major\}", r.get("naming", "")) or not re.fullmatch(r"[A-Za-z]*\d+\.\d+", str(r.get("start", ""))):
        problems.append("releases.naming needs {major} and releases.start must look like 'V1.0'")
    if not isinstance(cfg["agents"].get("max_concurrent"), int) or cfg["agents"]["max_concurrent"] < 1:
        problems.append("agents.max_concurrent must be a whole number of at least 1")
    seen = set()
    for g in cfg["gates"]:
        if not isinstance(g, dict) or not g.get("key") or not isinstance(g.get("minutes", 0), (int, float)):
            problems.append(f"gate {g!r} needs a key and numeric minutes")
            continue
        if g["key"] in seen:
            problems.append(f"gate {g['key']} is listed twice")
        seen.add(g["key"])
        if not isinstance(g.get("triggers", []), list):
            problems.append(f"gate {g['key']}: triggers must be a list of path patterns")
    from .board import section_problems    # the board section's own fields (VH-584); the page's limits are checked at seed time
    problems += section_problems(cfg)
    pids = set()
    for p in cfg["people"]:
        if not isinstance(p, dict) or not p.get("id") or not isinstance(p.get("hours_per_week"), (int, float)) or p["hours_per_week"] < 0:
            problems.append(f"person {p!r} needs an id and hours_per_week")
            continue
        if p["id"] in pids:
            problems.append(f"person {p['id']} is listed twice")
        pids.add(p["id"])
    if problems:
        raise ConfigError(problems)
    return cfg


def matches(path, patterns):
    return any(fnmatch.fnmatch(path, pat) for pat in patterns)


def item_gates(item, cfg):
    """The set of gate keys an item makes necessary. Fails closed: an item that names neither files nor gates
    triggers every gate, because an unclassified change treated as a cheap one is the failure to avoid."""
    keys = [g["key"] for g in cfg["gates"]]
    if item.get("gates") is not None:
        return {k for k in item["gates"] if k in keys}
    files = item.get("files") or []
    if not files:
        return set(keys)
    return {g["key"] for g in cfg["gates"] if any(matches(f, g.get("triggers", [])) for f in files)}


def normalise_item(raw, cfg):
    """One item, checked. Returns (item, problems)."""
    problems = []
    ref = raw.get("ref")
    if not ref or not isinstance(ref, str):
        return None, ["an item has no ref"]
    minutes = raw.get("minutes", 0)
    if not isinstance(minutes, (int, float)) or isinstance(minutes, bool) or minutes < 0:
        problems.append(f"{ref}: minutes must be a non-negative number")
        minutes = 0
    pr = raw.get("priority")
    if pr is not None and pr not in PRIORITY_RANK:
        problems.append(f"{ref}: priority {pr!r} is not high, med or low")
    it = {
        "ref": ref,
        "minutes": minutes,
        "priority": pr if pr in PRIORITY_RANK else None,
        "rank": PRIORITY_RANK.get(pr, 3),
        "state": raw.get("state", "open"),
        "kind": raw.get("kind", "build"),
        "deps": list(raw.get("deps") or []),
        "files": list(raw.get("files") or []),
        "lock": raw.get("lock"),
        "needs_owner": bool(raw.get("needs_owner")),
        "who": raw.get("who", "agent"),
        "human_minutes": raw.get("human_minutes", 0) or 0,
        "risk": bool(raw.get("risk")),
        "group": raw.get("group"),     # a theme: items in the release's anchor theme are preferred at equal priority
        "order": raw.get("order", 1e9),  # the person's own sequence; smaller comes first among equals
        "track": raw.get("track", "store"),  # "tooling" work ships no store artefact and is planned apart
        "task": raw.get("task", ""),
    }
    it["gates"] = sorted(item_gates(raw, cfg))
    it["risk_score"] = (10 * len(it["gates"]) + (25 if it["risk"] else 0)
                        + (15 if any(matches(f, cfg["risk_paths"]) for f in it["files"]) else 0))
    return it, problems


def release_name(cfg, index):
    m = re.fullmatch(r"([A-Za-z]*)(\d+)\.(\d+)", cfg["releases"]["start"])
    major, minor = int(m.group(2)), int(m.group(3)) + index
    return cfg["releases"]["naming"].format(major=major, minor=minor)
