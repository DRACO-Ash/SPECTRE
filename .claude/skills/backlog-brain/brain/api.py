"""One call from settings, items and measured rows to a plan with forecasts."""
from .model import load_config, normalise_item
from .optimiser import plan as make_plan
from .resources import pace_table, forecast


def run(raw_config, raw_items, pace_rows=None):
    cfg = load_config(raw_config)
    table = pace_table(pace_rows or [])
    overall = table.get("all")
    pace = overall["p50"] if overall and overall["n"] >= 3 else None   # measured median sizes the plan once there is evidence
    result = make_plan(raw_items, cfg, pace)
    by = {}
    for raw in raw_items:
        it, _ = normalise_item(raw, cfg)
        if it:
            by[it["ref"]] = it
    result["forecasts"] = [forecast(rel, by, cfg, table) for rel in result["releases"]]
    for f in result["forecasts"]:
        result["warnings"] += f["warnings"]
    result["pace_used"] = pace if pace is not None else cfg["releases"]["pace"]
    result["pace_source"] = "measured median of everything" if pace is not None else "settings (nothing measured yet)"
    return result
