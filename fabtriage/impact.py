"""What the benchmark numbers would mean on a fab floor, per 100 alarms.

Every number here rests on the assumptions below. They are illustrative, stated up front,
and easy to change; they are not measurements from a real fab.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import sim

ASSUMPTIONS = {
    "engineer_hours_per_manual_investigation": (
        2.5,
        "A practicing fab data scientist told us false-alarm holds are usually cleared in 2 to 3 hours.",
    ),
    "engineer_hours_per_review": (
        0.17,
        "About 10 minutes to read a disposition with cited evidence and approve or reject it (our estimate).",
    ),
    "lot_hours_per_needless_hold": (
        2.5,
        "A needlessly held lot waits as long as the investigation that clears it.",
    ),
    "lots_at_risk_per_missed_fault": (
        round(1 / sim.MEASURE_PROB, 1),
        "In the simulator about half of lots are sampled, so a missed chamber fault runs about two more "
        "lots before the next measured wafer can catch it.",
    ),
}


def per_100(summary: dict, rows: list, manual: bool) -> dict:
    n = max(summary["n"], 1)
    a = {k: v for k, (v, _) in ASSUMPTIONS.items()}
    escalated = sum(1 for r in rows if r.get("status") in ("needs_engineer", "turn_limit", "error"))
    if manual:  # every alarm is investigated by hand
        engineer = 100 * a["engineer_hours_per_manual_investigation"]
    else:  # every disposition is reviewed; escalations are investigated by hand
        engineer = 100 * a["engineer_hours_per_review"] + 100 * escalated / n * a["engineer_hours_per_manual_investigation"]
    return {
        "engineer_hours": round(engineer, 1),
        "needless_holds": round(100 * summary["needless_holds"] / n, 1),
        "lot_hours_from_needless_holds": round(100 * summary["needless_holds"] / n * a["lot_hours_per_needless_hold"], 1),
        "lot_hours_from_measurements": round(100 * summary["avg_lot_delay_h"], 1),
        "missed_faults": round(100 * summary["missed_faults"] / n, 1),
        "lots_at_risk": round(100 * summary["missed_faults"] / n * a["lots_at_risk_per_missed_fault"], 1),
    }


def table(runs_dir: Path, split: str) -> dict:
    out = {"split": split, "assumptions": {k: {"value": v, "why": w} for k, (v, w) in ASSUMPTIONS.items()}, "methods": {}}
    for path in sorted(runs_dir.glob(f"results_*_{split}.json")):
        data = json.loads(path.read_text())
        out["methods"][data["method"]] = per_100(data["summary"], data["rows"], manual=data["method"] == "always_hold")
    return out
