"""Confidence intervals for the benchmark.

    python -m fabtriage report --split holdout3

Each case counts once. When a method ran several times, its per-case result is the mean over
repeats, and intervals come from a bootstrap over cases (so repeats don't pretend to be new
cases). Comparisons between methods are paired: the same cases, resampled together.
Writes runs/report_<split>.json for the console.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from . import recovery as R
from . import sim

B = 10_000
DIAG_METHODS = ["agent", "agent_baseten", "agent_llama", "agent_noverify", "oneshot", "playbook", "always_hold"]
REC_METHODS = ["agent", "agent_baseten", "agent_llama", "agent_hide-history", "agent_hide-pm_detail", "agent_hide-history-pm_detail",
               "monitor_rule", "reset_recipe", "keep_recipe"]


def _rows(runs_dir: Path, label: str, split: str) -> list:
    """All repeats of a method on a split, as a list of row lists."""
    out = []
    first = runs_dir / f"results_{label}_{split}.json"
    if first.exists():
        out.append(json.loads(first.read_text())["rows"])
    rep_root = runs_dir / "repeats"
    if rep_root.exists():
        for d in sorted(rep_root.glob("r*")):
            f = d / f"results_{label}_{split}.json"
            if f.exists():
                out.append(json.loads(f.read_text())["rows"])
    return out


def per_case(repeats: list, ids: list, key, as_float=float) -> np.ndarray | None:
    """Mean over repeats of key(row) for each case id, in the order of ids. None if any case is missing."""
    vals = []
    for cid in ids:
        xs = [as_float(key(r)) for rows in repeats for r in rows if r["case_id"] == cid and key(r) is not None]
        if not xs:
            return None
        vals.append(float(np.mean(xs)))
    return np.array(vals)


def boot_ci(x: np.ndarray, seed: int = 0) -> tuple:
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(x), (B, len(x)))
    means = x[idx].mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def wilson(k: float, n: int, z: float = 1.96) -> tuple:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return float(max(0.0, c - h)), float(min(1.0, c + h))


def _fmt(v, pct=False):
    return round(float(v) * 100, 1) if pct else round(float(v), 2)


def diagnosis(runs_dir: Path, split: str) -> dict:
    ids = sim.benchmark(split)
    out = {"n_cases": len(ids), "methods": {}, "paired": {}}
    acc = {}
    for m in DIAG_METHODS:
        reps = _rows(runs_dir, m, split)
        if not reps:
            continue
        a = per_case(reps, ids, lambda r: r["decision_correct"])
        if a is None:
            out["methods"][m] = {"incomplete": True, "repeats": len(reps)}
            continue
        miss = per_case(reps, ids, lambda r: r["missed_fault"])
        need = per_case(reps, ids, lambda r: r["needless_hold"])
        always = int(np.sum(a == 1.0))
        lo, hi = boot_ci(a)
        if a.min() == a.max():  # a bootstrap of identical values has zero width; fall back to Wilson on cases
            lo, hi = wilson(always, len(a))
        out["methods"][m] = {
            "repeats": len(reps),
            "decision_accuracy_pct": _fmt(a.mean(), True),
            "ci95_pct": [_fmt(lo, True), _fmt(hi, True)],
            "wilson95_pct_if_single_run": [_fmt(v, True) for v in wilson(a.sum(), len(a))],
            "cases_always_right": always,
            "missed_faults_per_run": _fmt(miss.sum()),
            "needless_holds_per_run": _fmt(need.sum()),
        }
        acc[m] = a
    if "agent" in acc:
        for other in ("playbook", "oneshot", "agent_noverify", "always_hold"):
            if other in acc:
                d = acc["agent"] - acc[other]
                lo, hi = boot_ci(d, seed=1)
                out["paired"][f"agent_minus_{other}_pct"] = {"diff": _fmt(d.mean(), True), "ci95": [_fmt(lo, True), _fmt(hi, True)]}
    return out


def recovery(runs_dir: Path, split: str) -> dict:
    rdir = runs_dir / "recovery"
    ids = R.benchmark(split)
    out = {"n_cases": len(ids), "methods": {}, "paired": {}}
    off = {}
    for m in REC_METHODS:
        reps = _rows(rdir, m, split)
        if not reps:
            continue
        o = per_case(reps, ids, lambda r: r["off_target_lots"])
        if o is None:
            out["methods"][m] = {"incomplete": True, "repeats": len(reps)}
            continue
        oos = per_case(reps, ids, lambda r: r["out_of_spec_lots"])
        mon = per_case(reps, ids, lambda r: r["monitor_wafers"])
        lo, hi = boot_ci(o)
        out["methods"][m] = {
            "repeats": len(reps),
            "off_target_per_recovery": _fmt(o.mean()),
            "ci95": [_fmt(lo), _fmt(hi)],
            "off_target_total_per_run": _fmt(o.sum()),
            "out_of_spec_total_per_run": _fmt(oos.sum()),
            "monitor_wafers_per_recovery": _fmt(mon.mean()),
        }
        off[m] = o
    if "agent" in off:
        for other in ("monitor_rule", "reset_recipe", "keep_recipe"):
            if other in off:
                d = off["agent"] - off[other]
                lo, hi = boot_ci(d, seed=2)
                out["paired"][f"agent_minus_{other}_off_target_per_recovery"] = {"diff": _fmt(d.mean()), "ci95": [_fmt(lo), _fmt(hi)]}
    return out


def report(runs_dir: Path, split: str) -> dict:
    data = {"split": split, "diagnosis": diagnosis(runs_dir, split), "recovery": recovery(runs_dir, split)}
    (runs_dir / f"report_{split}.json").write_text(json.dumps(data, indent=2))
    return data


def sweep(runs_dir: Path, prefix: str = "stress") -> dict:
    """Per stress level: right-decision rate (diagnosis) and off-target lots per recovery, with 95% intervals."""
    out = {"levels": [0, 1, 2, 3], "prefix": prefix, "diagnosis": {}, "recovery": {}}
    for m in ["agent", "agent_baseten", "agent_llama", "oneshot", "playbook", "always_hold"]:
        row = []
        for lv in range(4):
            split = f"{prefix}_L{lv}"
            reps = _rows(runs_dir, m, split)
            a = per_case(reps, sim.benchmark(split), lambda r: r["decision_correct"]) if reps else None
            if a is None:
                row.append(None)
                continue
            lo, hi = boot_ci(a)
            if a.min() == a.max():
                lo, hi = wilson(int(np.sum(a == 1.0)), len(a))
            miss = per_case(reps, sim.benchmark(split), lambda r: r["missed_fault"])
            row.append({"decision_accuracy_pct": _fmt(a.mean(), True), "ci": [_fmt(lo, True), _fmt(hi, True)], "missed_faults": _fmt(miss.sum()), "n": len(a)})
        if any(row):
            out["diagnosis"][m] = row
    for m in ["agent", "agent_v2", "agent_baseten", "agent_llama", "monitor_rule", "reset_recipe", "keep_recipe", "oracle"]:
        row = []
        for lv in range(4):
            split = f"{prefix}_L{lv}"
            reps = _rows(runs_dir / "recovery", m, split)
            o = per_case(reps, R.benchmark(split), lambda r: r["off_target_lots"]) if reps else None
            if o is None:
                row.append(None)
                continue
            lo, hi = boot_ci(o)
            oos = per_case(reps, R.benchmark(split), lambda r: r["out_of_spec_lots"])
            mon = per_case(reps, R.benchmark(split), lambda r: r["monitor_wafers"])
            row.append({"off_target_per_recovery": _fmt(o.mean()), "ci": [_fmt(lo), _fmt(hi)], "out_of_spec": _fmt(oos.sum()), "monitors": _fmt(mon.mean()), "n": len(o)})
        if any(row):
            out["recovery"][m] = row
    (runs_dir / ("sweep.json" if prefix == "stress" else f"sweep_{prefix}.json")).write_text(json.dumps(out, indent=2))
    return out
