"""Benchmark for the recovery job.

    python -m fabtriage recover --method monitor_rule --split dev
    python -m fabtriage recover --method agent --split holdout --repeats 3
    python -m fabtriage recover-report --split holdout

Runs land in runs/recovery/<method>/<case>/run.json; results in
runs/recovery/results_<method>_<split>.json. The success criteria are in docs/RECOVERY.md.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from . import recovery as R

MODEL_METHODS = ("agent",)


def _label(method, backend, hide=()):
    label = method if backend in (None, "meta") or method not in MODEL_METHODS else f"{method}_{backend}"
    if hide:
        label += "_hide-" + "-".join(sorted(hide))
    return label


def run_one(method, case_id, runs_dir: Path, client=None, backend=None, autosave=False, hide=()) -> dict:
    case = R.load(case_id)
    label = _label(method, backend, hide)
    job = R.RecoveryJob(case, runs_dir / label / case_id)
    job.hide = set(hide)
    job.autosave = autosave
    job.live_extra = {"method": label, "live": True}
    extra = {}
    t0 = time.time()
    if method == "agent":
        from .agent import run_agent

        extra.update(run_agent(job, client, backend=backend))
    else:
        R.BASELINES[method](job)
    extra["seconds"] = round(time.time() - t0, 1)
    row, out = R.score(job)
    row["tokens"] = extra.get("tokens", 0)
    job.save({"method": label, "score": row, "outcome": out, **extra})
    return row


def summarize(rows: list) -> dict:
    n = len(rows) or 1
    ns = [r for r in rows if r["case_id"].startswith("rec_no_shift")]
    return {
        "n": len(rows),
        "off_target_lots": sum(r["off_target_lots"] for r in rows),
        "off_target_per_case": round(sum(r["off_target_lots"] for r in rows) / n, 2),
        "out_of_spec_lots": sum(r["out_of_spec_lots"] for r in rows),
        "avg_monitor_wafers": round(sum(r["monitor_wafers"] for r in rows) / n, 2),
        "avg_downtime_h": round(sum(r["downtime_h"] for r in rows) / n, 2),
        "needs_engineer": sum(1 for r in rows if r["status"] != "released"),
        "rule_broken_cases": sum(1 for r in rows if r["rule_broken"]),
        "no_shift_max_change_pct": max((abs(r["recipe_change_pct"]) for r in ns), default=None),
        "avg_tool_calls": round(sum(r["tool_calls"] for r in rows) / n, 2),
        "total_tokens": sum(r.get("tokens", 0) for r in rows),
    }


def write_results(label, split, runs_dir: Path, rows: list) -> dict:
    path = runs_dir / f"results_{label}_{split}.json"
    merged = {}
    if path.exists():
        merged = {r["case_id"]: r for r in json.loads(path.read_text()).get("rows", [])}
    for r in rows:
        merged[r["case_id"]] = r
    ordered = [merged[c] for c in R.benchmark(split) if c in merged]
    result = {"method": label, "split": split, "summary": summarize(ordered), "rows": ordered}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2))
    return result


def _saved(runs_dir: Path, label: str, case_id: str):
    path = runs_dir / label / case_id / "run.json"
    if path.exists():
        try:
            data = json.loads(path.read_text())
        except ValueError:
            return None
        if data.get("score") and data.get("status") in ("released", "needs_engineer"):
            return data["score"]
    return None


def run_split(method, split, runs_dir: Path, client=None, backend=None, only=None, hide=(), resume=False) -> dict:
    ids = R.benchmark(split)
    if only:
        ids = [i for i in ids if any(i.removeprefix("rec_").startswith(o) for o in only)]
    rows = []
    for cid in ids:
        row = _saved(runs_dir, _label(method, backend, hide), cid) if resume else None
        if row is None:
            row = run_one(method, cid, runs_dir, client, backend, hide=hide)
        print(
            f"{cid:26s} status={row['status']:14s} off_target={row['off_target_lots']:2d} oos={row['out_of_spec_lots']} "
            f"monitors={row['monitor_wafers']} change={row['recipe_change_pct']}% calls={row['tool_calls']}",
            flush=True,
        )
        rows.append(row)
    return write_results(_label(method, backend, hide), split, runs_dir, rows)


def run_repeats(method, split, runs_dir: Path, repeats: int, client=None, backend=None, hide=(), resume=False) -> dict:
    label = _label(method, backend, hide)
    summaries = []
    for k in range(1, repeats + 1):
        print(f"--- repeat {k} of {repeats}", flush=True)
        where = runs_dir if k == 1 else runs_dir / "repeats" / f"r{k}"
        summaries.append(run_split(method, split, where, client, backend, hide=hide, resume=resume)["summary"])
    keys = ["off_target_lots", "out_of_spec_lots", "avg_monitor_wafers", "avg_downtime_h", "needs_engineer", "no_shift_max_change_pct", "avg_tool_calls"]
    mean_std = {}
    for k in keys:
        vals = [float(s.get(k) or 0) for s in summaries]
        m = sum(vals) / len(vals)
        sd = (sum((v - m) ** 2 for v in vals) / (len(vals) - 1)) ** 0.5 if len(vals) > 1 else 0.0
        mean_std[k] = {"mean": round(m, 2), "std": round(sd, 2), "max": max(vals)}
    out = {"method": label, "split": split, "repeats": repeats, "summaries": summaries, "mean_std": mean_std}
    (runs_dir / f"results_{label}_{split}_repeats.json").write_text(json.dumps(out, indent=2))
    return out


ABLATIONS = ["agent_hide-history", "agent_hide-pm_detail", "agent_hide-history-pm_detail"]


def load_results(runs_dir: Path, split: str) -> dict:
    out = {}
    for m in ["agent", "agent_baseten", *ABLATIONS, "monitor_rule", "reset_recipe", "keep_recipe"]:
        path = runs_dir / f"results_{m}_{split}.json"
        if path.exists():
            data = json.loads(path.read_text())
            rep = runs_dir / f"results_{m}_{split}_repeats.json"
            if rep.exists():
                data["repeats"] = json.loads(rep.read_text())
            out[m] = data
    return out


def criteria(results: dict) -> list:
    """The five success criteria from docs/RECOVERY.md. Uses repeat means (worst repeat for safety ones)."""
    if "agent" not in results:
        return []
    a = results["agent"]
    ms = (a.get("repeats") or {}).get("mean_std")
    off = ms["off_target_lots"]["mean"] if ms else a["summary"]["off_target_lots"]
    oos_worst = ms["out_of_spec_lots"]["max"] if ms else a["summary"]["out_of_spec_lots"]
    mon = ms["avg_monitor_wafers"]["mean"] if ms else a["summary"]["avg_monitor_wafers"]
    ns = ms["no_shift_max_change_pct"]["max"] if ms else (a["summary"]["no_shift_max_change_pct"] or 0)
    keep = results.get("keep_recipe", {}).get("summary", {}).get("off_target_lots")
    guides = [results[m]["summary"]["off_target_lots"] for m in ("monitor_rule", "reset_recipe") if m in results]
    out = []
    if keep is not None:
        out.append({"criterion": "at least 30% fewer off-target lots than keep_recipe", "value": f"{off} vs {keep}", "met": off <= 0.7 * keep})
    if guides:
        out.append({"criterion": "no more off-target lots than the best guide rule", "value": f"{off} vs {min(guides)}", "met": off <= min(guides)})
    out.append({"criterion": "no out-of-spec lots caused (worst repeat)", "value": oos_worst, "met": oos_worst == 0})
    out.append({"criterion": "at most 3 monitor wafers per recovery on average", "value": mon, "met": mon <= 3})
    out.append({"criterion": "no_shift recipe change at most 1% (worst repeat)", "value": ns, "met": ns <= 1})
    return out
