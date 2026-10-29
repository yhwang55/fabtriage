"""Score dispositions against the hidden truth, and run a method over a benchmark split.

Metrics per case:
  cause_correct      the root-cause category matches
  decision_correct   every required action is there and no forbidden action is
  missed_fault       a real fault where the alarm lot was not held
  needless_hold      a hold (lot or chamber) that the truth didn't call for
  accepted           the disposition passed verification (vs. sent to an engineer)
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from . import sim
from .tools import Investigation


def score(case: sim.Case, inv: Investigation) -> dict:
    truth = case.truth
    d = inv.disposition or {"cause": None, "actions": []}
    actions = {(a.get("type"), a.get("target")) for a in d["actions"] if isinstance(a, dict)}
    kinds = {k for k, _ in actions}
    required = {tuple(r) for r in truth["required"]}
    forbidden = set(truth["forbidden"])
    lot = case.alarm["lot_id"]
    holds = {(k, t) for k, t in actions if k in ("hold_lot", "hold_chamber")}
    needed_holds = {r for r in required if r[0] in ("hold_lot", "hold_chamber")}
    return {
        "case_id": case.case_id,
        "scenario": case.scenario,
        "status": inv.status,
        "accepted": inv.status == "awaiting_signoff",
        "cause": d.get("cause"),
        "true_cause": truth["cause"],
        "cause_correct": d.get("cause") == truth["cause"],
        "decision_correct": required <= actions and not (kinds & forbidden),
        "missed_fault": truth["real_fault"] and ("hold_lot", lot) not in actions,
        "needless_hold": bool(holds - needed_holds),
        "confounder": truth.get("confounder"),
        **inv.costs(),
    }


def summarize(rows: list) -> dict:
    n = len(rows) or 1

    def rate(key):
        return round(sum(1 for r in rows if r[key]) / n, 3)

    return {
        "n": len(rows),
        "cause_accuracy": rate("cause_correct"),
        "decision_accuracy": rate("decision_correct"),
        "missed_faults": sum(1 for r in rows if r["missed_fault"]),
        "needless_holds": sum(1 for r in rows if r["needless_hold"]),
        "accepted_rate": rate("accepted"),
        "avg_tool_calls": round(sum(r["tool_calls"] for r in rows) / n, 2),
        "avg_measurements": round(sum(r["measurements"] for r in rows) / n, 2),
        "avg_lot_delay_h": round(sum(r["lot_delay_h"] for r in rows) / n, 2),
        "total_tokens": sum(r.get("tokens", 0) for r in rows),
    }


def run_one(
    method: str,
    case_id: str,
    runs_dir: Path,
    client=None,
    backend=None,
    sam_client=None,
    engineer_note=None,
    autosave=False,
    keep: dict | None = None,
) -> dict:
    case = sim.load(case_id)
    run_dir = runs_dir / method / case_id
    inv = Investigation(case, run_dir, client=sam_client if method == "agent" else None)
    inv.autosave = autosave
    inv.live_extra = {"method": method, "live": True, **(keep or {})}
    extra = dict(keep or {})
    t0 = time.time()
    if method == "agent":
        from .agent import run_agent

        extra.update(run_agent(inv, client, backend=backend, engineer_note=engineer_note))
    else:
        from .baselines import BASELINES

        BASELINES[method](inv)
    extra["seconds"] = round(time.time() - t0, 1)
    row = score(case, inv)
    row["tokens"] = extra.get("tokens", 0)
    inv.save({"method": method, "score": row, **extra})
    return row


def run_split(
    method: str, split: str, runs_dir: Path, client=None, backend=None, limit=None, only=None, sam_client=None
) -> dict:
    ids = sim.benchmark(split)
    if only:
        ids = [i for i in ids if any(i.startswith(o) for o in only)]
    if limit:
        ids = ids[:limit]
    rows = []
    for cid in ids:
        row = run_one(method, cid, runs_dir, client, backend, sam_client)
        mark = "ok " if row["decision_correct"] else "BAD"
        print(
            f"{mark} {cid:20s} cause={row['cause']!s:10s} truth={row['true_cause']:10s} "
            f"status={row['status']:16s} calls={row['tool_calls']:2d} meas={row['measurements']}",
            flush=True,
        )
        rows.append(row)
    return write_results(method, split, runs_dir, rows)


def write_results(method: str, split: str, runs_dir: Path, rows: list, fresh: bool = False) -> dict:
    """Merge rows into results_<method>_<split>.json: a partial rerun replaces only its own cases."""
    out = runs_dir / f"results_{method}_{split}.json"
    merged = {}
    if out.exists() and not fresh:
        for r in json.loads(out.read_text()).get("rows", []):
            merged[r["case_id"]] = r
    for r in rows:
        merged[r["case_id"]] = r
    order = sim.benchmark(split)
    all_rows = [merged[c] for c in order if c in merged]
    result = {"method": method, "split": split, "summary": summarize(all_rows), "rows": all_rows}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2))
    return result


def rescore(method: str, split: str, runs_dir: Path) -> dict:
    """Rebuild the results file from the saved run.json files."""
    rows = []
    for cid in sim.benchmark(split):
        path = runs_dir / method / cid / "run.json"
        if path.exists():
            score = json.loads(path.read_text()).get("score")
            if score:
                rows.append(score)
    return write_results(method, split, runs_dir, rows, fresh=True)
