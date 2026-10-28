"""The board page's settings and the batch that seeds a new board (VH-584). Standard library only.

The page (assets/board/board.html) reads one settings document, board/settings, and falls back field by field to what it
drew before settings existed: PAGE_DEFAULTS, the Vendor Fishing board's values on 2026-10-07. A field that is absent
keeps that value; a field set to null switches the feature off (no store, no round rule). The pack writes the document
from a project's settings record, validated here, so a value the page would have to ignore never reaches it.

Two sets of checks. section_problems runs inside load_config: the board section's own fields, so a record with a broken
section is refused whole like any other. page_problems runs only where a board is built (board settings, board seed, guide
--config): the limits the page itself enforces on the rest of the record. The planner never needed those, so a record that
planned before still plans (a Dockerfile gate keyed "build" by an older installer included); only seeding a board refuses it.

The guide (assets/how-to-use.json) carries a few tokens, filled from the same settings on the page and in
`brain.py guide`: {floor} and {cap} (hours), {ref} (the ref prefix), {source} (where the pipeline is read from) and
{overhead} (the fixed work every release costs, in words). A job marked "when": "store" is left out when there is no store.
"""
import math
import re

SCHEMA = 1
# What the page draws with no board/settings document. The page holds the same object (BOARD_DEFAULTS) and
# tests/test_board_settings.py fails if the two part.
PAGE_DEFAULTS = {
    "schema": SCHEMA,
    "organisation": "Bluestaq Limited",
    "project": "Vendor Fishing",
    "refPrefix": "VH-",
    "budget": {"floorMin": 720, "capMin": 840},
    "overheadMin": 375,
    "store": {"name": "App Store"},
    "rounds": {"limit": 4, "label": "two-round rule, 2 gates × 2 rounds"},
    "horizon": 4,
    "sync": {"staleMin": 90, "refreshWaitMin": 15, "idleChecks": 3},
    "source": {"name": "delivery", "detail": "gate table, eval record and commits", "command": "sync_pipeline.py",
               "onRelease": "Tell delivery and run the documentation liaison."},
}
# A new project's board, where its settings record says nothing: no organisation line, no store, no round rule.
NEW_BOARD = {"organisation": "", "store": None, "rounds": None, "horizon": 4,
             "sync": {"stale_min": 90, "refresh_wait_min": 15, "idle_checks": 3},
             "source": {"name": "delivery", "detail": "", "command": "", "on_release": ""}}
RESERVED_GATES = ("build", "upload")     # the page draws Build itself and treats Upload as the store's answer
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
TOKEN = re.compile(r"\{(floor|cap|ref|source|overhead)\}")
URL = re.compile(r"^https://claude\.ai/(code/)?artifact/[A-Za-z0-9-]{8,64}$")
DOC_ID = re.compile(r"^(?!\.\.?$)[A-Za-z0-9_\-.~:@+]{1,200}$")   # ArtifactData's document id rule, so a seed batch is never refused whole
PREFIX = re.compile(r"^[A-Za-z0-9]{1,11}-?$")                     # the page's own test for a ref prefix
SECTION_KEYS = {"organisation", "store", "rounds", "horizon", "sync", "source", "url"}
MAX_MIN = 100000                                                  # the page's upper bound for a minutes figure


def _units(v):
    """Length as the page measures it (UTF-16 code units), so a name the pack accepts is never one the page drops."""
    return len(v.encode("utf-16-le")) // 2


def _text(v, limit, where, problems, empty_ok=True):
    if not isinstance(v, str) or _units(v) > limit or CONTROL.search(v) or (not empty_ok and not v.strip()):
        problems.append(f"{where} must be {'' if empty_ok else 'non-empty '}text of at most {limit} characters on one line")
        return False
    return True


def _whole(v, lo, hi, where, problems):
    if not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi:
        problems.append(f"{where} must be a whole number from {lo} to {hi}")
        return False
    return True


def section_problems(cfg):
    """Problems with a settings record's optional board section. Called by load_config, so a broken section refuses the record."""
    problems = []
    b = cfg.get("board")
    if b is None:
        b = {}
    if not isinstance(b, dict):
        return ["board must be an object"]
    for k in sorted(set(b) - SECTION_KEYS):
        problems.append(f"board.{k} is not a board setting (they are {', '.join(sorted(SECTION_KEYS))})")
    if "organisation" in b:
        _text(b["organisation"], 80, "board.organisation", problems)
    if b.get("store") is not None:
        s = b["store"]
        if not isinstance(s, dict) or set(s) - {"name"}:
            problems.append("board.store must be null or {\"name\": ...}")
        else:
            _text(s.get("name"), 40, "board.store.name", problems, empty_ok=False)
    if b.get("rounds") is not None:
        s = b["rounds"]
        if not isinstance(s, dict) or set(s) - {"limit", "label"}:
            problems.append("board.rounds must be null or {\"limit\": ..., \"label\": ...}")
        else:
            _whole(s.get("limit"), 1, 50, "board.rounds.limit", problems)
            _text(s.get("label"), 80, "board.rounds.label", problems, empty_ok=False)
    if "horizon" in b:
        _whole(b["horizon"], 0, 12, "board.horizon", problems)
    sy = b.get("sync", {})
    if not isinstance(sy, dict) or set(sy) - {"stale_min", "refresh_wait_min", "idle_checks"}:
        problems.append("board.sync takes stale_min, refresh_wait_min and idle_checks")
    else:
        for k, hi in (("stale_min", 10080), ("refresh_wait_min", 1440), ("idle_checks", 100)):
            if k in sy:
                _whole(sy[k], 1, hi, f"board.sync.{k}", problems)
    so = b.get("source", {})
    if not isinstance(so, dict) or set(so) - {"name", "detail", "command", "on_release"}:
        problems.append("board.source takes name, detail, command and on_release")
    else:
        for k, n in (("name", 40), ("detail", 120), ("command", 80), ("on_release", 200)):
            if k in so:
                _text(so[k], n, f"board.source.{k}", problems, empty_ok=k != "name")
    if b.get("url") is not None and not (isinstance(b["url"], str) and URL.match(b["url"])):
        problems.append("board.url must be the board's claude.ai artifact link")
    return problems


def page_problems(cfg):
    """What the board page needs of the rest of a record that load_config has accepted: the limits the page enforces itself,
    release names it can extend (V<major>.<minor>, owner decision D2), gate keys the store accepts as document ids, and none
    of the two keys the page draws itself. Run only where a board is built."""
    problems = []
    p, r = cfg.get("project") or {}, cfg.get("releases") or {}
    _text(p.get("name"), 80, "project.name, for the board page,", problems, empty_ok=False)
    if not (isinstance(p.get("ref_prefix"), str) and PREFIX.match(p["ref_prefix"])):
        problems.append("project.ref_prefix must be 1 to 11 letters or digits and an optional hyphen for the board page")
    for k in ("floor_min", "cap_min", "overhead_min"):
        v = r.get(k)
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) or v != int(v) or not 0 <= v <= MAX_MIN:
            problems.append(f"releases.{k} must be whole minutes from 0 to {MAX_MIN} for the board page")
    if r.get("cap_min") == 0:
        problems.append("releases.cap_min must be above zero for the board page")
    if r.get("naming") != "V{major}.{minor}" or not re.fullmatch(r"V\d+\.\d+", str(r.get("start", ""))):
        problems.append("releases.naming must be V{major}.{minor} and releases.start like V1.0 for the board page")
    for g in cfg.get("gates") or []:
        k = g.get("key")
        if k in RESERVED_GATES:
            problems.append(f"gate key '{k}' is reserved: the page draws {'the build' if k == 'build' else 'the store upload'} itself"
                            + (" (an older installer keyed a Dockerfile gate 'build': rename it 'container')" if k == "build" else ""))
        elif not (isinstance(k, str) and DOC_ID.match(k)):
            problems.append(f"gate key {k!r} cannot be a board document id: use letters, digits and _ - . ~ : @ +")
        if g.get("lane") not in (None, "main", "review"):
            problems.append(f"gate {k}: lane must be main or review")
    return problems


def settings_doc(cfg):
    """The board/settings document for a settings record that load_config has already accepted. Raises ConfigError, with
    every problem listed, when the page could not draw the record as written."""
    from .model import ConfigError
    problems = page_problems(cfg)
    if problems:
        raise ConfigError(problems)
    b = dict(NEW_BOARD, **(cfg.get("board") or {}))
    sy = dict(NEW_BOARD["sync"], **(b.get("sync") or {}))
    so = dict(NEW_BOARD["source"], **(b.get("source") or {}))
    r = cfg["releases"]
    return {
        "schema": SCHEMA,
        "organisation": b["organisation"],
        "project": cfg["project"]["name"],
        "refPrefix": cfg["project"]["ref_prefix"],
        "budget": {"floorMin": int(r["floor_min"]), "capMin": int(r["cap_min"])},
        "overheadMin": int(r["overhead_min"]),
        "store": {"name": b["store"]["name"]} if b.get("store") else None,
        "rounds": {"limit": b["rounds"]["limit"], "label": b["rounds"]["label"]} if b.get("rounds") else None,
        "horizon": b["horizon"],
        "sync": {"staleMin": sy["stale_min"], "refreshWaitMin": sy["refresh_wait_min"], "idleChecks": sy["idle_checks"]},
        "source": {"name": so["name"], "detail": so["detail"], "command": so["command"], "onRelease": so["on_release"]},
    }


def hours_text(m):
    """Minutes as hours for the page's budget wording: 720 is "12", 810 is "13.5". Whole minutes never land on a rounding tie."""
    return f"{round(m / 60, 2):g}"


def overhead_text(m, store=True):
    """The fixed work every release costs, in words, for the guide's times job: 375 with a store is "a little over 6 hours of
    fixed work for checks, packaging and upload". Nothing measured (0) says so rather than naming an amount."""
    end = "upload" if store else "release"
    m = int(round(m or 0))
    if m <= 0:
        return f"fixed work for checks, packaging and {end}, not yet measured"
    if m < 60:
        dur = f"about {m} minutes"
    else:
        h, r = divmod(m, 60)
        hs = lambda n: f"{n} hour{'s' if n != 1 else ''}"
        dur = hs(h) if r == 0 else f"a little over {hs(h)}" if r < 30 else f"a little under {hs(h + 1)}"
    return f"{dur} of fixed work for checks, packaging and {end}"


def fill(text, s):
    s = s or PAGE_DEFAULTS
    vals = {"floor": hours_text(s["budget"]["floorMin"]), "cap": hours_text(s["budget"]["capMin"]), "ref": s["refPrefix"],
            "source": s["source"]["name"], "overhead": overhead_text(s["overheadMin"], bool(s.get("store")))}
    return TOKEN.sub(lambda mt: vals[mt.group(1)], text)


def fill_guide(g, s=None):
    """One audience of the guide with its tokens filled; a job marked "when": "store" is dropped when there is no store."""
    s = s or PAGE_DEFAULTS
    out = dict(g, title=fill(g["title"], s), intro=fill(g["intro"], s), who=[fill(w, s) for w in g.get("who", [])], jobs=[])
    for j in g["jobs"]:
        if j.get("when") == "store" and not s.get("store"):
            continue
        out["jobs"].append(dict(j, title=fill(j["title"], s), steps=[fill(x, s) for x in j["steps"]],
                                controls=[fill(c, s) for c in j.get("controls", [])]))
    if not g.get("who"):
        out.pop("who")
    return out


def plan_key(name):
    """The page's own key for a release name: r- and the name in lower case with runs of other characters as one hyphen."""
    return "r-" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def release_doc_id(name):
    """The page's releases document id for a release name (relDocId): V2.8 is 2-8-0."""
    parts = re.sub(r"^v", "", str(name), flags=re.I).split(".") + ["0", "0"]
    return "-".join(parts[:3])


def seed(cfg, now):
    """The ArtifactData batch a new board needs before its page can write: board/meta, board/settings, the current release
    and the horizon behind it, its releases row, and one gates document per gate (the store's upload last when there is a
    store). Every write creates a document, so none carries a version. cfg must already be accepted by load_config."""
    from .model import release_name
    s = settings_doc(cfg)
    names = [release_name(cfg, i) for i in range(s["horizon"] + 1)]
    writes = [{"op": "set", "collection": "board", "doc_id": "settings", "data": s},
              {"op": "set", "collection": "board", "doc_id": "meta", "data": {
                  "currentRelease": names[0], "nextRelease": names[1] if len(names) > 1 else "", "stageIndex": 0, "frozenAt": None,
                  "buildRate": cfg["releases"]["pace"], "releaseStepsMin": s["overheadMin"], "reviewFixesMin": 0,
                  "basis": "a release holds only checked, costed work", "updatedAt": now}}]
    for i, n in enumerate(names):
        writes.append({"op": "set", "collection": "plan", "doc_id": plan_key(n), "data": {
            "key": plan_key(n), "name": n, "status": "current" if i == 0 else "planned", "order": i,
            "focus": "Not yet planned"}})
    rid = release_doc_id(names[0])
    writes.append({"op": "set", "collection": "releases", "doc_id": rid,
                   "data": {"version": rid.replace("-", "."), "status": "current", "rounds": [], "order": 0}})
    gates = [g for g in cfg["gates"]]
    for i, g in enumerate(gates):
        doc = {"key": g["key"], "label": g.get("label") or g["key"], "short": g.get("short") or g.get("label") or g["key"],
               "lane": g.get("lane") or "main", "status": "pending", "rounds": [], "order": i + 1,
               "note": f"{names[0]} not started"}
        if g.get("minutes"):
            doc["minutes"] = g["minutes"]
        writes.append({"op": "set", "collection": "gates", "doc_id": g["key"], "data": doc})
    if s["store"]:
        writes.append({"op": "set", "collection": "gates", "doc_id": "upload", "data": {
            "key": "upload", "label": f"{s['store']['name']} upload", "short": "Upload", "lane": "main", "status": "pending",
            "rounds": [], "order": len(gates) + 1, "note": "Owner marks the store's answer"}})
    if len(writes) > 50:
        raise ValueError(f"the seed needs {len(writes)} writes and one batch holds 50: list fewer gates or a shorter horizon")
    return {"action": "batch", "writes": writes}
