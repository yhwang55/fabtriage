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


MODEL_METHODS = ("agent", "agent_noverify", "oneshot")


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
        "ungrounded_claims": any(p.startswith("claim") for p in inv.posthoc_problems),
        "playbook_rule_broken": any(p.startswith("rule:") for p in inv.posthoc_problems),
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
        "ungrounded_cases": sum(1 for r in rows if r.get("ungrounded_claims")),
        "rule_broken_cases": sum(1 for r in rows if r.get("playbook_rule_broken")),
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
    label = method if backend in (None, "meta") or method not in MODEL_METHODS else f"{method}_{backend}"
    run_dir = runs_dir / label / case_id
    uses_model = method in MODEL_METHODS
    inv = Investigation(case, run_dir, client=sam_client if uses_model else None)
    inv.verify_enabled = method not in ("agent_noverify", "oneshot")
    inv.autosave = autosave
    inv.live_extra = {"method": label, "live": True, **(keep or {})}
    extra = dict(keep or {})
    t0 = time.time()
    if method in ("agent", "agent_noverify"):
        from .agent import run_agent

        extra.update(run_agent(inv, client, backend=backend, engineer_note=engineer_note))
    elif method == "oneshot":
        from .oneshot import run_oneshot

        extra.update(run_oneshot(inv, client, backend=backend))
    else:
        from .baselines import BASELINES

        BASELINES[method](inv)
    extra["seconds"] = round(time.time() - t0, 1)
    row = score(case, inv)
    row["tokens"] = extra.get("tokens", 0)
    inv.save({"method": label, "score": row, **extra})
    return row


def run_repeats(
    method: str, split: str, runs_dir: Path, repeats: int, client=None, backend=None, sam_client=None, resume=False
) -> dict:
    """Run a split several times. Repeat 1 lands in the normal place (the console shows it);
    repeats 2..n go to runs/repeats/r<k>/. Writes results_<label>_<split>_repeats.json."""
    label = method if backend in (None, "meta") or method not in MODEL_METHODS else f"{method}_{backend}"
    summaries, per_case = [], {}
    for k in range(1, repeats + 1):
        print(f"--- repeat {k} of {repeats}", flush=True)
        where = runs_dir if k == 1 else runs_dir / "repeats" / f"r{k}"
        result = run_split(method, split, where, client, backend, sam_client=sam_client, resume=resume)
        summaries.append(result["summary"])
        for r in result["rows"]:
            per_case.setdefault(r["case_id"], []).append(bool(r["decision_correct"]))
    out = {
        "method": label,
        "split": split,
        "repeats": repeats,
        "summaries": summaries,
        "mean_std": spread(summaries),
        "cases_always_right": sum(1 for v in per_case.values() if all(v)),
        "cases_sometimes_wrong": {c: f"{sum(v)}/{len(v)}" for c, v in per_case.items() if not all(v)},
    }
    path = runs_dir / f"results_{label}_{split}_repeats.json"
    path.write_text(json.dumps(out, indent=2))
    return out


def spread(summaries: list) -> dict:
    keys = ["decision_accuracy", "cause_accuracy", "missed_faults", "needless_holds", "rule_broken_cases",
            "avg_tool_calls", "avg_measurements", "avg_lot_delay_h", "total_tokens"]
    out = {}
    for k in keys:
        vals = [float(s.get(k) or 0) for s in summaries]
        mean = sum(vals) / len(vals)
        var = sum((v - mean) ** 2 for v in vals) / (len(vals) - 1) if len(vals) > 1 else 0.0
        out[k] = {"mean": round(mean, 3), "std": round(var**0.5, 3)}
    return out


def _saved_row(runs_dir: Path, label: str, case_id: str):
    path = runs_dir / label / case_id / "run.json"
    if path.exists():
        try:
            data = json.loads(path.read_text())
        except ValueError:
            return None
        if data.get("score") and data.get("status") not in ("error", "running"):
            return data["score"]
    return None


def run_split(
    method: str, split: str, runs_dir: Path, client=None, backend=None, limit=None, only=None, sam_client=None, resume=False
) -> dict:
    ids = sim.benchmark(split)
    if only:
        ids = [i for i in ids if any(i.startswith(o) for o in only)]
    if limit:
        ids = ids[:limit]
    rows = []
    label = method if backend in (None, "meta") or method not in MODEL_METHODS else f"{method}_{backend}"
    for cid in ids:
        row = _saved_row(runs_dir, label, cid) if resume else None
        if row is None:
            row = run_one(method, cid, runs_dir, client, backend, sam_client)
        mark = "ok " if row["decision_correct"] else "BAD"
        print(
            f"{mark} {cid:20s} cause={row['cause']!s:10s} truth={row['true_cause']:10s} "
            f"status={row['status']:16s} calls={row['tool_calls']:2d} meas={row['measurements']}",
            flush=True,
        )
        rows.append(row)
    return write_results(label, split, runs_dir, rows)


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
