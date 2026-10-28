"""Resource and time model: people, agents, measured pace, and forecasts as ranges.

Nothing here is assumed that can be measured. Pace comes from finished items (estimated and actual minutes, who
did the work, what kind of work it was). Where too few rows exist for the exact person and kind, the lookup falls
back person-and-kind, then kind, then person, then everything, then the project's settings, and says which one it
used, so a forecast built on little evidence says so.
"""
import math

MIN_ROWS = 3  # fewer measured rows than this and a level of the lookup is not trusted


def _pct(sorted_vals, q):
    if not sorted_vals:
        return None
    x = (len(sorted_vals) - 1) * q
    lo, hi = math.floor(x), math.ceil(x)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (x - lo)


def pace_table(rows):
    """rows: dicts with est, actual (minutes) and optional who, kind. Returns {key: stats}."""
    groups = {}
    for r in rows:
        est, act = r.get("est"), r.get("actual")
        if not isinstance(est, (int, float)) or not isinstance(act, (int, float)) or est <= 0 or act <= 0:
            continue
        ratio = act / est
        who, kind = r.get("who"), r.get("kind")
        keys = ["all"]
        if who:
            keys.append(f"who:{who}")
        if kind:
            keys.append(f"kind:{kind}")
        if who and kind:
            keys.append(f"who:{who}|kind:{kind}")
        for k in keys:
            groups.setdefault(k, []).append(ratio)
    out = {}
    for k, v in groups.items():
        v.sort()
        out[k] = {"n": len(v), "p25": _pct(v, .25), "p50": _pct(v, .5), "p75": _pct(v, .75)}
    return out


def pick_pace(table, who, kind, cfg):
    """Best-evidence pace for this person and kind: (low, mid, high, source)."""
    for key, label in ((f"who:{who}|kind:{kind}", "person and kind"), (f"kind:{kind}", "kind"), (f"who:{who}", "person"), ("all", "everything")):
        s = table.get(key)
        if s and s["n"] >= MIN_ROWS:
            return s["p25"], s["p50"], s["p75"], f"{label} ({s['n']} measured)"
    p = cfg["releases"]["pace"]
    return p, p, p, "settings (nothing measured yet)"


def capacity_per_day(cfg):
    """Human minutes available per working day across all people, from hours per week."""
    days = cfg["working"]["days_per_week"]
    return sum(p["hours_per_week"] * 60 / days for p in cfg["people"])


def forecast(release, items_by_ref, cfg, table):
    """A release's wall-clock forecast as a range, plus the human time it asks for and a capacity check.

    Build time is the longest lane (lanes run at once, up to the agent limit); items in a lane run one after the
    other. Human minutes are the owner and reviewer time items declare, which no number of agents removes."""
    lane_ranges, notes, sources = [], [], set()
    seq = [0.0, 0.0, 0.0]
    for lane in release["lanes"]:
        lo = mid = hi = 0.0
        for ref in lane["refs"]:
            it = items_by_ref[ref]
            a, b, c, src = pick_pace(table, it.get("who", "agent"), it.get("kind", "build"), cfg)
            lo += it["minutes"] * a
            mid += it["minutes"] * b
            hi += it["minutes"] * c
            for j, v in enumerate((a, b, c)):
                seq[j] += it["minutes"] * v
            sources.add(src)
        lane_ranges.append((lo, mid, hi))
    build = tuple(max((r[i] for r in lane_ranges), default=0.0) for i in range(3))   # lanes run at once
    sequential = tuple(seq)                                                             # one stream, the board's basis
    from .optimiser import _overhead
    over = _overhead(cfg, set(release["gates"]))
    total = tuple(round(x + over, 1) for x in sequential)       # the headline is sequential, which is how releases are sized
    parallel_total = tuple(round(x + over, 1) for x in build)    # with the lanes at once; the saving agents buy
    human = sum(items_by_ref[r["ref"]].get("human_minutes", 0) for r in release["items"])
    per_day = capacity_per_day(cfg)
    days = parallel_total[1] / (cfg["working"]["hours_per_day"] * 60) if cfg["working"]["hours_per_day"] else 0
    avail = per_day * days
    warns = []
    if cfg["people"] and human > 0.8 * avail:
        warns.append(f"{release['name']}: needs {human:.0f} min of people's time in a window with about {avail:.0f} available; "
                     f"people, not agents, are the limit. Defer owner-heavy items or add capacity.")
    if not cfg["people"] and human:
        warns.append(f"{release['name']}: {human:.0f} min of people's time is declared but no people are configured")
    if len(release["lanes"]) > cfg["agents"]["max_concurrent"]:
        warns.append(f"{release['name']}: {len(release['lanes'])} lanes exceed the agent limit of {cfg['agents']['max_concurrent']}")
    return {"name": release["name"], "low_min": total[0], "mid_min": total[1], "high_min": total[2],
            "parallel_low_min": parallel_total[0], "parallel_mid_min": parallel_total[1], "parallel_high_min": parallel_total[2],
            "build_mid_min": round(sequential[1], 1), "overhead_min": over, "human_min": human,
            "working_days": round(days, 1), "pace_sources": sorted(sources), "warnings": warns}
