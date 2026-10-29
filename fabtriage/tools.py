"""The investigation tools. Every result gets an evidence id (E1, E2, ...) that the final
disposition must cite. All numbers are computed here, in plain code; the model only
decides what to look at and what to conclude.

    inv = Investigation(case, run_dir)
    result = inv.call("get_chamber_summary", {"window_hours": 24})
    inv.call("submit_disposition", {...})   # runs the verification layer
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from scipy import stats

from . import sim, verify, wafermap

MAX_MEASUREMENTS = 3
MAX_DISPOSITION_TRIES = 3
ACTIONS = ["hold_lot", "release_lot", "hold_chamber", "escalate_upstream", "hold_metrology_tool", "flag_sensor"]
CAUSES = ["chamber", "metrology", "upstream", "noise", "sensor"]


def _num(x, nd=2):
    return round(float(x), nd)


DEFINITIONS = [
    {
        "name": "get_alarm",
        "description": "The alarm that started this investigation, with spec and control limits.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "get_lot_history",
        "description": "Where one lot went: clean tool, deposition chamber, metrology tool, its FDC readings, "
        "wafers since PM on that chamber, and its measured mean if it was sampled.",
        "parameters": {
            "type": "object",
            "properties": {"lot_id": {"type": "string"}},
            "required": ["lot_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "query_lots",
        "description": "List recent lots as a compact table (lot, time, clean tool, chamber, metrology tool, "
        "measured mean), optionally filtered by tool. Use it instead of reading lots one at a time.",
        "parameters": {
            "type": "object",
            "properties": {
                "window_hours": {"type": "number", "description": "default 12"},
                "chamber": {"type": "string"},
                "clean_tool": {"type": "string"},
                "met_tool": {"type": "string"},
                "measured_only": {"type": "boolean", "description": "default true"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_chamber_summary",
        "description": "Box-plot statistics of measured wafer means for every deposition chamber over a recent "
        "window, with OOC/OOS counts and PM status. Use it to see whether one chamber stands out.",
        "parameters": {
            "type": "object",
            "properties": {"window_hours": {"type": "number", "description": "default 24"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "get_trend",
        "description": "Time series for one chamber: measured thickness, or one FDC parameter. Includes the "
        "mean before and after the last PM in the window and the slope against wafers since PM.",
        "parameters": {
            "type": "object",
            "properties": {
                "chamber": {"type": "string"},
                "signal": {
                    "type": "string",
                    "enum": ["thickness"] + list(sim.FDC_PARAMS),
                },
                "window_hours": {"type": "number", "description": "default 24"},
            },
            "required": ["chamber", "signal"],
            "additionalProperties": False,
        },
    },
    {
        "name": "run_commonality",
        "description": "Commonality analysis over recently measured lots: for each step (CLEAN, DEP, MET), "
        "the mean thickness per tool and a one-way ANOVA p-value. A small p-value at one step means lots "
        "that went through one tool at that step differ from the rest.",
        "parameters": {
            "type": "object",
            "properties": {"window_hours": {"type": "number", "description": "default 12"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "get_fdc_summary",
        "description": "FDC sensor summary for one chamber: each parameter's recent mean against its own "
        "baseline, as a z-score, and the thickness of wafers measured in the same recent window.",
        "parameters": {
            "type": "object",
            "properties": {
                "chamber": {"type": "string"},
                "recent_hours": {"type": "number", "description": "default 4"},
            },
            "required": ["chamber"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_pm_log",
        "description": "Preventive maintenance events in the last 72 hours, for one chamber or all.",
        "parameters": {
            "type": "object",
            "properties": {"chamber": {"type": "string"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "request_measurement",
        "description": f"Measure (or re-measure) a lot's sampled wafer on a metrology tool. Costs "
        f"{sim.REMEASURE_DELAY_H} hours of lot delay each, at most {MAX_MEASUREMENTS} per investigation. "
        "Only lots from the last 12 hours can still be measured.",
        "parameters": {
            "type": "object",
            "properties": {
                "lot_id": {"type": "string"},
                "met_tool": {"type": "string", "enum": sim.MET_TOOLS},
            },
            "required": ["lot_id", "met_tool"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_wafer_map",
        "description": "Within-wafer thickness map of a measured lot, segmented by SAM 3.1: where the wafer is "
        "thick relative to its own mean (center, edge ring, local spot). Shows shape, not overall offset.",
        "parameters": {
            "type": "object",
            "properties": {"lot_id": {"type": "string"}},
            "required": ["lot_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "submit_disposition",
        "description": "File your conclusion for engineer sign-off. Checked by code before it is accepted: "
        "every claim must cite an evidence id and every number in a claim must appear in that evidence. "
        f"Refused dispositions come back with the problems; after {MAX_DISPOSITION_TRIES} refusals the case goes "
        "to an engineer.",
        "parameters": {
            "type": "object",
            "properties": {
                "cause": {"type": "string", "enum": CAUSES},
                "actions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string", "enum": ACTIONS},
                            "target": {
                                "type": "string",
                                "description": "lot id, chamber, tool id, or chamber:parameter for flag_sensor",
                            },
                        },
                        "required": ["type", "target"],
                        "additionalProperties": False,
                    },
                },
                "claims": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "evidence_id": {"type": "string"},
                            "statement": {"type": "string"},
                        },
                        "required": ["evidence_id", "statement"],
                        "additionalProperties": False,
                    },
                },
                "summary": {"type": "string", "description": "two or three sentences for the engineer"},
            },
            "required": ["cause", "actions", "claims", "summary"],
            "additionalProperties": False,
        },
    },
]


class Investigation:
    def __init__(self, case: sim.Case, run_dir: Path | None = None, client=None):
        self.case = case
        self.run_dir = Path(run_dir) if run_dir else None
        self.client = client  # for SAM; None means local segmentation
        self.evidence: dict = {}
        self.trace: list = []
        self.measurements: list = []  # {"lot_id", "met_tool", "mean", "in_spec"}
        self.tries = 0
        self.status = "running"
        self.disposition = None
        self.refusals: list = []
        self.verify_enabled = True  # False only for the ablation: problems are recorded but not enforced
        self.posthoc_problems: list = []
        self.notes: list = []  # the agent's visible reasoning, {"step": n, "text": ...}
        self.autosave = False  # write run.json after every tool call (live view in the console)
        self.live_extra: dict = {}

    # ---------------------------------------------------------------- dispatch
    def call(self, name: str, args: dict) -> dict:
        args = args or {}
        if self.status != "running":
            return {"error": f"investigation is closed ({self.status})"}
        handler = getattr(self, "t_" + name, None)
        if handler is None:
            result = {"error": f"unknown tool {name!r}"}
        else:
            try:
                result = handler(**args)
            except TypeError as error:
                result = {"error": f"bad arguments: {error}"}
            except (KeyError, ValueError) as error:
                result = {"error": str(error)}
        if name != "submit_disposition" and "error" not in result:
            eid = f"E{len(self.evidence) + 1}"
            result = {"evidence_id": eid, **result}
            self.evidence[eid] = {"tool": name, "args": args, "result": result}
        self.trace.append({"tool": name, "args": args, "result": result})
        if self.autosave:
            self.save(self.live_extra)
        return result

    def costs(self) -> dict:
        return {
            "tool_calls": len(self.trace),
            "measurements": len(self.measurements),
            "lot_delay_h": _num(sim.REMEASURE_DELAY_H * len(self.measurements), 1),
            "disposition_tries": self.tries,
        }

    # ---------------------------------------------------------------- helpers
    def _recent(self, hours, measured=True):
        start = self.case.now_h - float(hours)
        return [
            lot
            for lot in self.case.lots
            if lot["time_h"] > start and (lot["measurement"] is not None or not measured)
        ]

    def _chamber(self, chamber):
        if chamber not in sim.CHAMBERS:
            raise ValueError(f"unknown chamber {chamber!r}; chambers are {sim.CHAMBERS}")
        return chamber

    def _last_pm(self, chamber, before=None):
        before = self.case.now_h if before is None else before
        pms = [p["time_h"] for p in self.case.pm_log if p["chamber"] == chamber and p["time_h"] <= before]
        return max(pms) if pms else None

    # ---------------------------------------------------------------- tools
    def t_get_alarm(self):
        return {
            "alarm": self.case.alarm,
            "spec_limits": [sim.LSL, sim.USL],
            "control_limits": [sim.LCL, sim.UCL],
            "target": sim.TARGET,
            "now_h": self.case.now_h,
        }

    def t_get_lot_history(self, lot_id):
        lot = self.case.lot(lot_id)
        out = {
            "lot_id": lot_id,
            "time_h": lot["time_h"],
            "clean_tool": lot["clean_tool"],
            "chamber": lot["chamber"],
            "met_tool": lot["met_tool"] if lot["measurement"] else None,
            "wafers_since_pm_on_chamber": lot["wafers_since_pm"],
            "fdc": lot["fdc"],
            "measured": lot["measurement"] is not None,
        }
        if lot["measurement"]:
            out["measured_mean_A"] = lot["measurement"]["mean"]
            out["measured_range_A"] = lot["measurement"]["range"]
        return out

    def t_query_lots(self, window_hours=12, chamber=None, clean_tool=None, met_tool=None, measured_only=True):
        if chamber:
            self._chamber(chamber)
        rows = []
        for lot in self._recent(window_hours, measured=bool(measured_only)):
            if chamber and lot["chamber"] != chamber:
                continue
            if clean_tool and lot["clean_tool"] != clean_tool:
                continue
            m = lot["measurement"]
            if met_tool and (m is None or m["met_tool"] != met_tool):
                continue
            rows.append(
                [lot["lot_id"], lot["time_h"], lot["clean_tool"], lot["chamber"], m["met_tool"] if m else None, m["mean"] if m else None]
            )
        return {
            "window_hours": window_hours,
            "columns": ["lot_id", "time_h", "clean_tool", "chamber", "met_tool", "mean_A"],
            "n": len(rows),
            "rows": rows[-40:],
        }

    def t_get_chamber_summary(self, window_hours=24):
        lots = self._recent(window_hours)
        rows = {}
        for c in sim.CHAMBERS:
            vals = np.array([lot["measurement"]["mean"] for lot in lots if lot["chamber"] == c])
            last_pm = self._last_pm(c)
            row = {
                "n_measured": int(len(vals)),
                "hours_since_last_pm": _num(self.case.now_h - last_pm, 1) if last_pm is not None else "no PM in 72h",
                "wafers_since_pm_now": max([lot["wafers_since_pm"] for lot in self.case.lots if lot["chamber"] == c]),
            }
            if len(vals):
                q1, med, q3 = np.percentile(vals, [25, 50, 75])
                row.update(
                    {
                        "mean_A": _num(vals.mean()),
                        "std_A": _num(vals.std(ddof=1)) if len(vals) > 1 else 0.0,
                        "min_A": _num(vals.min()),
                        "q1_A": _num(q1),
                        "median_A": _num(med),
                        "q3_A": _num(q3),
                        "max_A": _num(vals.max()),
                        "n_ooc": int(((vals > sim.UCL) | (vals < sim.LCL)).sum()),
                        "n_oos": int(((vals > sim.USL) | (vals < sim.LSL)).sum()),
                    }
                )
            rows[c] = row
        return {"window_hours": window_hours, "chambers": rows}

    def t_get_trend(self, chamber, signal, window_hours=24):
        chamber = self._chamber(chamber)
        if signal != "thickness" and signal not in sim.FDC_PARAMS:
            raise ValueError(f"unknown signal {signal!r}")
        lots = [lot for lot in self._recent(window_hours, measured=(signal == "thickness")) if lot["chamber"] == chamber]
        if signal == "thickness":
            pts = [(lot["time_h"], lot["measurement"]["mean"], lot) for lot in lots]
        else:
            pts = [(lot["time_h"], lot["fdc"][signal], lot) for lot in lots]
        out = {"chamber": chamber, "signal": signal, "window_hours": window_hours, "n_points": len(pts)}
        if not pts:
            return out
        values = np.array([p[1] for p in pts])
        out["points"] = [
            {"time_h": t, "lot_id": lot["lot_id"], "value": _num(v, 3 if signal == "pressure_Torr" else 2)}
            for t, v, lot in pts[-20:]
        ]
        out["mean"] = _num(values.mean(), 3)
        out["last_value"] = _num(values[-1], 3)
        pm = self._last_pm(chamber)
        if pm is not None and pm > self.case.now_h - window_hours:
            before = [v for t, v, _ in pts if t < pm]
            after = [v for t, v, _ in pts if t >= pm]
            out["last_pm_h"] = pm
            out["mean_before_pm"] = _num(np.mean(before), 3) if before else None
            out["mean_after_pm"] = _num(np.mean(after), 3) if after else None
            out["n_after_pm"] = len(after)
        if signal == "thickness" and len(pts) >= 4:
            wafers = np.array([lot["wafers_since_pm"] for _, _, lot in pts], dtype=float)
            if np.ptp(wafers) > 0:
                slope = np.polyfit(wafers / 100.0, values, 1)[0]
                out["slope_A_per_100_wafers"] = _num(slope, 3)
            half = len(values) // 2
            out["mean_first_half"] = _num(values[:half].mean())
            out["mean_second_half"] = _num(values[half:].mean())
        return out

    def t_run_commonality(self, window_hours=12):
        lots = self._recent(window_hours)
        steps = {"CLEAN": "clean_tool", "DEP": "chamber", "MET": "met_tool"}
        out = {"window_hours": window_hours, "n_lots": len(lots), "steps": {}}
        overall = float(np.mean([lot["measurement"]["mean"] for lot in lots])) if lots else 0.0
        for step, key in steps.items():
            groups = {}
            for lot in lots:
                groups.setdefault(lot[key], []).append(lot["measurement"]["mean"])
            usable = [g for g in groups.values() if len(g) >= 2]
            p = float(stats.f_oneway(*usable).pvalue) if len(usable) >= 2 else None
            per_tool = {
                k: {"n": len(v), "mean_A": _num(np.mean(v))} for k, v in sorted(groups.items())
            }
            worst = max(groups, key=lambda k: abs(np.mean(groups[k]) - sim.TARGET)) if groups else None
            out["steps"][step] = {
                "per_tool": per_tool,
                "anova_p_value": _num(p, 4) if p is not None and not np.isnan(p) else None,
                "most_deviant_tool": worst,
            }
        out["overall_mean_A"] = _num(overall)
        return out

    def t_get_fdc_summary(self, chamber, recent_hours=4):
        chamber = self._chamber(chamber)
        now = self.case.now_h
        lots = [lot for lot in self.case.lots if lot["chamber"] == chamber]
        recent = [lot for lot in lots if lot["time_h"] > now - recent_hours]
        base = [lot for lot in lots if now - 48 < lot["time_h"] <= now - recent_hours]
        params = {}
        for p in sim.FDC_PARAMS:
            b = np.array([lot["fdc"][p] for lot in base])
            r = np.array([lot["fdc"][p] for lot in recent])
            if len(b) < 3 or len(r) == 0:
                continue
            z = (r.mean() - b.mean()) / (b.std(ddof=1) / np.sqrt(len(r)))
            nd = 4 if p == "pressure_Torr" else 2
            params[p] = {
                "baseline_mean": _num(b.mean(), nd),
                "recent_mean": _num(r.mean(), nd),
                "delta": _num(r.mean() - b.mean(), nd),
                "z_score": _num(z, 1),
            }
        measured = [lot for lot in recent if lot["measurement"] is not None]
        return {
            "chamber": chamber,
            "recent_hours": recent_hours,
            "n_recent_runs": len(recent),
            "parameters": params,
            "recent_measured_wafers": [
                {"lot_id": lot["lot_id"], "mean_A": lot["measurement"]["mean"]} for lot in measured
            ],
        }

    def t_get_pm_log(self, chamber=None):
        if chamber:
            self._chamber(chamber)
        events = [p for p in self.case.pm_log if chamber in (None, p["chamber"])]
        return {"now_h": self.case.now_h, "events": events}

    def t_request_measurement(self, lot_id, met_tool):
        lot = self.case.lot(lot_id)
        if met_tool not in sim.MET_TOOLS:
            raise ValueError(f"unknown metrology tool {met_tool!r}")
        if len(self.measurements) >= MAX_MEASUREMENTS:
            return {"error": f"measurement budget used up ({MAX_MEASUREMENTS})"}
        if lot["time_h"] < self.case.now_h - 12:
            return {"error": "lot is older than 12 hours and has moved on; it can't be measured"}
        m = sim.remeasure(self.case, lot_id, met_tool, len(self.measurements))
        in_spec = sim.LSL <= m["mean"] <= sim.USL
        self.measurements.append({"lot_id": lot_id, "met_tool": met_tool, "mean": m["mean"], "in_spec": in_spec})
        lot.setdefault("_remeasures", []).append(m)
        return {
            "lot_id": lot_id,
            "wafer_id": lot["wafer_id"],
            "met_tool": met_tool,
            "mean_A": m["mean"],
            "range_A": m["range"],
            "in_spec": in_spec,
            "in_control": sim.LCL <= m["mean"] <= sim.UCL,
            "lot_delay_added_h": sim.REMEASURE_DELAY_H,
        }

    def t_get_wafer_map(self, lot_id):
        lot = self.case.lot(lot_id)
        m = (lot.get("_remeasures") or [None])[-1] or lot["measurement"]
        if m is None:
            return {"error": f"{lot_id} has no measurement; request_measurement first"}
        out_dir = (self.run_dir or Path("runs/_maps")) / "maps"
        image = wafermap.render(m["sites"], out_dir / f"{lot_id}.png")
        summary = wafermap.summarize(m["sites"], image, self.client)
        return {"lot_id": lot_id, "met_tool": m["met_tool"], "mean_A": m["mean"], **summary}

    def t_submit_disposition(self, cause, actions, claims, summary):
        self.tries += 1
        disposition = {"cause": cause, "actions": actions, "claims": claims, "summary": summary}
        problems = verify.check(self, disposition)
        if not self.verify_enabled:  # ablation: accept anything, but keep what the verifier would have said
            self.posthoc_problems = problems
            self.disposition = disposition
            self.status = "awaiting_signoff"
            return {"accepted": True, "status": "awaiting_signoff", "note": "Sent to the engineer for sign-off."}
        if not problems:
            self.disposition = disposition
            self.status = "awaiting_signoff"
            return {"accepted": True, "status": "awaiting_signoff", "note": "Sent to the engineer for sign-off."}
        self.refusals.append({"try": self.tries, "problems": problems, "disposition": disposition})
        if self.tries >= MAX_DISPOSITION_TRIES:
            self.disposition = disposition
            self.status = "needs_engineer"
            return {"accepted": False, "status": "needs_engineer", "problems": problems}
        return {
            "accepted": False,
            "problems": problems,
            "tries_left": MAX_DISPOSITION_TRIES - self.tries,
        }

    # ---------------------------------------------------------------- saving
    def save(self, extra: dict | None = None) -> Path | None:
        if self.run_dir is None:
            return None
        self.run_dir.mkdir(parents=True, exist_ok=True)
        path = self.run_dir / "run.json"
        data = {
            "case_id": self.case.case_id,
            "alarm": self.case.alarm,
            "status": self.status,
            "disposition": self.disposition,
            "refusals": self.refusals,
            "verifier_enabled": self.verify_enabled,
            "posthoc_problems": self.posthoc_problems,
            "costs": self.costs(),
            "trace": self.trace,
            "notes": self.notes,
            "truth": self.case.truth,  # stored for review only; never shown to the agent
            **(extra or {}),
        }
        path.write_text(json.dumps(data, indent=2, default=str))
        return path
