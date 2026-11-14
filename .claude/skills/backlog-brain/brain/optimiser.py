"""The optimiser: compose releases and a build order from a backlog.

Deterministic: the same items and settings always give the same plan. Every placement carries a plain-English
reason. It never moves an item a person locked to a release, never places an item before its dependencies, and
never silently overfills a release: an item that cannot fit anywhere is placed alone and reported.

How a release is filled, in order:
  1. Locked items first (a person placed them by name).
  2. The highest-priority class still waiting, preferring items that add no new gate (a gate is a review or check
     whose cost is paid once per release, so items sharing gates share that cost).
  3. Riders: lower-priority items whose gates the release already pays for, so they cost no extra gate.
  4. If the release is still under its floor and the settings allow it, the cheapest-gate items regardless of
     priority, so a release is never cut half empty while work waits.
"""
from .model import PRIORITY_RANK, DONE_STATES, OFF_PATH_KINDS, normalise_item, release_name, matches


def _overhead(cfg, gates_used):
    r = cfg["releases"]
    if not r["overhead_min"]:
        return 0
    if not r["gate_savings"]:
        return r["overhead_min"]
    saved = sum(g.get("minutes", 0) for g in cfg["gates"] if g["key"] not in gates_used)
    return max(0, r["overhead_min"] - saved)


def forecast_min(cfg, priced, gates_used, pace=None):
    """Wall-clock minutes from the start of build to handover for a release of this size and gate set."""
    p = cfg["releases"]["pace"] if pace is None else pace
    return priced * p + _overhead(cfg, gates_used)


def _levels(items):
    """Dependency depth for ordering inside a release; a cycle is cut and reported."""
    by = {i["ref"]: i for i in items}
    depth, state, cycles = {}, {}, []

    def visit(ref, trail):
        if ref in depth:
            return depth[ref]
        if state.get(ref) == 1:
            cycles.append(" -> ".join(trail + [ref]))
            return 0
        state[ref] = 1
        d = 0
        for dep in by[ref]["deps"]:
            if dep in by:
                d = max(d, visit(dep, trail + [ref]) + 1)
        state[ref] = 2
        depth[ref] = d
        return d

    for r in sorted(by):
        visit(r, [])
    return depth, cycles


def plan(raw_items, cfg, pace=None, max_releases=50):
    warnings, items = [], []
    for raw in raw_items:
        it, problems = normalise_item(raw, cfg)
        warnings += problems
        if it:
            items.append(it)
    refs = {i["ref"] for i in items}
    done = {i["ref"] for i in items if i["state"] in DONE_STATES}
    live = [i for i in items if i["state"] not in DONE_STATES]
    tooling = [i for i in live if i["track"] == "tooling" and i["kind"] not in OFF_PATH_KINDS]
    pool = [i for i in live if i["kind"] in OFF_PATH_KINDS]
    waiting = [i for i in live if i["needs_owner"] and i not in pool]
    cand = [i for i in live if i not in pool and i not in waiting and i not in tooling]
    for i in cand:
        for d in i["deps"]:
            if d not in refs:
                warnings.append(f"{i['ref']}: depends on {d}, which is not in the backlog")
    waiting_refs = {i["ref"] for i in waiting} | {i["ref"] for i in pool}
    depth, cycles = _levels(cand)
    warnings += [f"dependency cycle: {c}" for c in cycles]
    p = cfg["releases"]["pace"] if pace is None else pace
    cap, floor = cfg["releases"]["cap_min"], cfg["releases"]["floor_min"]
    # Fill towards a target below the cap, so a release has margin; the cap itself is only broken by a lock or an item too big for any release.
    target = cfg["releases"].get("target_min") or floor + 0.75 * (cap - floor)
    placed, releases = {}, []
    by = {i["ref"]: i for i in cand}

    def ready(i, this):
        return all(d in done or d in placed or d in this or d not in refs for d in i["deps"]) \
            and not any(d in waiting_refs for d in i["deps"])

    def fits(priced, gates, limit=None):
        return forecast_min(cfg, priced, gates, p) <= (target if limit is None else limit)

    k = 0
    unplaced = lambda: [i for i in cand if i["ref"] not in placed]
    while unplaced() and k < max_releases:
        name = release_name(cfg, k)
        this, gates, priced, reasons = [], set(), 0, {}
        ref_set = set()
        anchor = [None]   # the theme of the first item picked; later picks prefer it

        def add(i, why):
            nonlocal priced
            if anchor[0] is None and i["group"]:
                anchor[0] = i["group"]
            this.append(i)
            ref_set.add(i["ref"])
            gates.update(i["gates"])
            priced += i["minutes"]
            reasons[i["ref"]] = why
            placed[i["ref"]] = name

        for i in sorted(unplaced(), key=lambda x: x["ref"]):
            if i["lock"] == name:
                add(i, f"locked to {name} by a person")
                if not fits(priced, gates, cap):
                    warnings.append(f"{name}: locked items alone take {forecast_min(cfg, priced, gates, p):.0f} min, over the {cap} cap")
        # main pass: best priority class first, fewest new gates first
        while True:
            avail = [i for i in unplaced() if i["lock"] is None and ready(i, ref_set)]
            if not avail:
                break
            pick, blocked = None, None
            # the person's own sequence first, then priority, then the release's theme, then the cheapest new gates
            for i in sorted(avail, key=lambda x: (x["order"], x["rank"],
                                                  0 if (anchor[0] is None or x["group"] == anchor[0]) else 1,
                                                  sum(g["minutes"] for g in cfg["gates"] if g["key"] in set(x["gates"]) - gates),
                                                  x["minutes"], x["ref"])):
                key = (i["order"], i["rank"])
                adds_gate = bool(set(i["gates"]) - gates)
                # a lower-priority item does not get to pay for a new gate while a more urgent one is left waiting
                if adds_gate and blocked is not None and key > blocked:
                    continue
                if fits(priced + i["minutes"], gates | set(i["gates"])):
                    pick = i
                    break
                if blocked is None:
                    blocked = key
            if not pick:
                break
            new = sorted(set(pick["gates"]) - gates)
            rider = bool(this) and not new and pick["rank"] > min(x["rank"] for x in this)
            why = (f"rider: priority {pick['priority'] or 'unset'}, adds no gate" if rider
                   else f"priority {pick['priority'] or 'unset'}" + (f", adds gate {', '.join(new)}" if new and this else ""))
            add(pick, why + ("; anchors the release" if not this else ""))
        # riders: lower priority, no new gate
        grew = True
        while grew:
            grew = False
            for i in sorted((x for x in unplaced() if x["lock"] is None and ready(x, ref_set)), key=lambda x: (x["rank"], x["ref"])):
                if set(i["gates"]) <= gates and fits(priced + i["minutes"], gates):
                    add(i, f"rider: priority {i['priority'] or 'unset'}, adds no gate")
                    grew = True
                    break
        # fill to the floor
        if cfg["releases"]["fill_to_floor"]:
            while forecast_min(cfg, priced, gates, p) < floor:
                opts = [i for i in unplaced() if i["lock"] is None and ready(i, ref_set) and fits(priced + i["minutes"], gates | set(i["gates"]), cap)]
                if not opts:
                    break
                i = sorted(opts, key=lambda x: (sum(g["minutes"] for g in cfg["gates"] if g["key"] in set(x["gates"]) - gates), x["rank"], x["ref"]))[0]
                add(i, "fills the release to its floor")
        if not this:
            # nothing fits: place the most urgent ready item alone and say so, never loop and never drop it
            rest = [i for i in unplaced() if ready(i, ref_set) and i["lock"] in (None, name)]
            if not rest:
                if any(i["lock"] and i["lock"] != name for i in unplaced()):
                    k += 1
                    continue
                for i in unplaced():
                    warnings.append(f"{i['ref']}: cannot be placed, its dependencies never become ready")
                    placed[i["ref"]] = None
                break
            i = sorted(rest, key=lambda x: (x["rank"], x["ref"]))[0]
            add(i, "placed alone: it does not fit any release")
            warnings.append(f"{i['ref']}: needs {forecast_min(cfg, i['minutes'], set(i['gates']), p):.0f} min, over the {cap} cap on its own")
        order = sorted(this, key=lambda x: (depth.get(x["ref"], 0), -x["risk_score"], x["rank"], x["ref"]))
        releases.append({
            "name": name,
            "items": [{"ref": i["ref"], "minutes": i["minutes"], "reason": reasons[i["ref"]], "gates": i["gates"]} for i in order],
            "priced": priced,
            "gates": sorted(gates),
            "forecast_min": round(forecast_min(cfg, priced, gates, p), 1),
            "lanes": lanes(order, cfg),
        })
        k += 1
    stranded = []
    for i in unplaced():   # still unplaced after the loop: locked to a release this plan never reaches (VH-461)
        why = f"locked to {i['lock']}, a release this plan never reaches, so it is in no release"
        warnings.append(f"{i['ref']}: {why}")
        stranded.append({"ref": i["ref"], "why": why})
    tooling_out = {"items": [{"ref": i["ref"], "minutes": i["minutes"]} for i in sorted(tooling, key=lambda x: (x["rank"], x["order"], x["ref"]))],
                   "priced": sum(i["minutes"] for i in tooling), "build_min": round(sum(i["minutes"] for i in tooling) * p, 1),
                   "note": "ships no store artefact, so carries no release overhead"}
    return {"releases": releases, "tooling": tooling_out, "waiting": [{"ref": i["ref"], "why": "needs an owner answer"} for i in waiting] + stranded,
            "off_path": [{"ref": i["ref"], "why": f"{i['kind']}: no release gate"} for i in pool], "warnings": warnings}


def lanes(order, cfg):
    """Group a release's items into lanes whose files do not overlap, then pack them onto the agent limit.
    Items that touch the same file must be built one after the other, so they share a lane."""
    parent = {i["ref"]: i["ref"] for i in order}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    owner = {}
    for i in order:
        for f in i["files"]:
            if f in owner:
                parent[find(i["ref"])] = find(owner[f])
            else:
                owner[f] = i["ref"]
    groups = {}
    for i in order:
        groups.setdefault(find(i["ref"]), []).append(i)
    comps = sorted(groups.values(), key=lambda g: (-sum(x["minutes"] for x in g), g[0]["ref"]))
    n = max(1, cfg["agents"]["max_concurrent"])
    bins = [{"refs": [], "minutes": 0} for _ in range(min(n, len(comps)) or 1)]
    for g in comps:
        b = min(bins, key=lambda b: (b["minutes"], len(b["refs"])))
        b["refs"] += [x["ref"] for x in g]
        b["minutes"] += sum(x["minutes"] for x in g)
    return [b for b in bins if b["refs"]]
