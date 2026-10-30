"""The engineer's send-back loop, measured.

    python -m fabtriage feedback --split stress_L3

Takes every alarm the agent got wrong on a split (from its saved results), and investigates
each one again twice: once with a short engineer note attached, once with nothing (so plain
run-to-run variation is not mistaken for the effect of the note). One fixed note for every
case; it says what an engineer would say without knowing the answer, and never names the
true cause. Results go to runs/feedback/<split>/ and runs/feedback_<split>.json.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import evaluate, sim

NOTE = (
    "Not approved. The disposition holds equipment without conclusive evidence. At this noise level a "
    "chamber-to-chamber comparison alone is not decisive. Before holding a chamber or a lot, check the "
    "film directly: a re-measurement of the alarm wafer on the other metrology tool, the wafer map, or "
    "the measured lots on this chamber right before and after the alarm. If the film is fine, release. If the "
    "film really is off, find which step is responsible before holding equipment."
)


def wrong_cases(runs_dir: Path, split: str, method: str = "agent") -> list:
    path = runs_dir / f"results_{method}_{split}.json"
    rows = json.loads(path.read_text())["rows"]
    return [r for r in rows if not r["decision_correct"]]


def run(split: str, runs_dir: Path, client, backend: str = "meta", sam_client=None, resume: bool = False) -> dict:
    wrong = wrong_cases(runs_dir, split)
    out = {"split": split, "note": NOTE, "cases": [], "n": len(wrong)}
    for cond, note in (("with_note", NOTE), ("no_note", None)):
        where = runs_dir / "feedback" / split / cond
        for r in wrong:
            cid = r["case_id"]
            saved = evaluate._saved_row(where, "agent", cid) if resume else None
            row = saved or evaluate.run_one(
                "agent", cid, where, client, backend, sam_client, engineer_note=note,
                keep={"engineer_note": note, "first_disposition": {"cause": r["cause"], "needless_hold": r["needless_hold"], "missed_fault": r["missed_fault"]}},
            )
            print(f"{cond:9s} {cid:24s} first={r['cause']!s:10s} now={row['cause']!s:10s} truth={row['true_cause']:10s} {'ok ' if row['decision_correct'] else 'BAD'}", flush=True)
            out["cases"].append({"condition": cond, "case_id": cid, "first_cause": r["cause"], "cause": row["cause"], "true_cause": row["true_cause"],
                                 "decision_correct": row["decision_correct"], "needless_hold": row["needless_hold"], "missed_fault": row["missed_fault"],
                                 "tool_calls": row["tool_calls"], "measurements": row["measurements"]})
    for cond in ("with_note", "no_note"):
        rows = [c for c in out["cases"] if c["condition"] == cond]
        out[cond] = {
            "fixed": sum(1 for c in rows if c["decision_correct"]),
            "still_wrong": sum(1 for c in rows if not c["decision_correct"]),
            "new_missed_faults": sum(1 for c in rows if c["missed_fault"]),
            "avg_measurements": round(sum(c["measurements"] for c in rows) / max(1, len(rows)), 2),
            "avg_tool_calls": round(sum(c["tool_calls"] for c in rows) / max(1, len(rows)), 2),
        }
    (runs_dir / f"feedback_{split}.json").write_text(json.dumps(out, indent=2))
    return out
