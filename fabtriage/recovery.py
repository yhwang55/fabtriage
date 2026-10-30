"""Recovery after PM: bring a held chamber back to target and release it.

FabTriage's diagnosis ends with "hold the chamber". This module starts there. Whoever does
the recovery (a fixed rule or the agent) reads the PM record and the chamber's history, may
run a few monitor wafers, sets the recipe time and the controller settings, and releases the
chamber. Then 40 production lots run under an EWMA run-to-run controller and are scored on
the true film thickness.

The idea comes from Prof. Jang (The Catholic University of Korea): R2R models need many runs
and lose their footing after PM, so engineers re-center recipes by guide rules and experience.

    case = recovery.load("rec_seasoning-3")
    inv = RecoveryJob(case, run_dir)
    inv.call("get_recovery_brief", {})
    ...
    inv.call("release_chamber", {...})       # runs the verification layer
    outcome = recovery.run_out(case, inv)     # what the next 40 lots would have looked like

Every random draw that is not a decision (wafer noise, which lots are measured, on which
tool) comes from the case seed, so all methods face exactly the same luck.
"""

from __future__ import annotations

import json
import zlib
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import sim, verify

TARGET = sim.TARGET
T_NOM = 60.0  # baseline recipe time after a clean PM, seconds
R_NOM = TARGET / T_NOM  # nominal deposition rate, angstrom per second
N_LOTS = 40
LOT_NOISE = 1.5  # lot-to-lot film noise, angstrom
MET_NOISE = 0.8
NOISE_SCALE = {0: 1.0, 1: 1.4, 2: 1.8, 3: 2.2}  # stress levels: film and metrology noise multiplier
STRESS_SEEDS = list(range(19, 24))
MAX_MONITORS = 4
MONITOR_DOWNTIME_H = 0.5
ENGINEER_FALLBACK_H = 2.5  # a refused recovery goes to an engineer
DEFAULT_LAMBDA = 0.3
DEFAULT_MONITOR_TOOL = "MET02"  # where monitor wafers are routed unless someone asks otherwise
MAX_CHANGE = 0.08  # the playbook caps a single recipe change at 8%
MAX_TRIES = 3

SCENARIOS = ["post_pm_reset", "seasoning", "fast_drift", "metrology_bias", "no_shift"]
DEV_SEEDS = [1, 2, 3, 4]
HOLDOUT_SEEDS = [5, 6]  # run once on Oct 29; one run in 30 exposed the drift sign mix-up
HOLDOUT2_SEEDS = [7, 8]  # fresh set for the version with the sign rule
HOLDOUT3_SEEDS = list(range(9, 19))  # large held-out set (50 recoveries), for confidence intervals
LINKED_FROM = [f"pm_shift-{s}" for s in sim.DEV_SEEDS]  # recoveries that continue a diagnosis; not in the benchmark


def benchmark(split: str = "dev") -> list:
    if split == "linked":
        return [f"rec_after_{d}" for d in LINKED_FROM]
    if split.startswith("stress_L"):
        level = int(split.removeprefix("stress_L"))
        tag = "" if level == 0 else f"@L{level}"
        return [f"rec_{s}{tag}-{seed}" for s in SCENARIOS for seed in STRESS_SEEDS]
    seeds = {
        "dev": DEV_SEEDS,
        "holdout": HOLDOUT_SEEDS,
        "holdout2": HOLDOUT2_SEEDS,
        "holdout3": HOLDOUT3_SEEDS,
        "all": DEV_SEEDS + HOLDOUT_SEEDS + HOLDOUT2_SEEDS + HOLDOUT3_SEEDS,
    }[split]
    return [f"rec_{s}-{seed}" for s in SCENARIOS for seed in seeds]


@dataclass
class RecoveryCase:
    case_id: str
    scenario: str
    seed: int
    chamber: str
    pm: dict  # the PM record the recoverer can read
    pre_pm_time_s: float
    history: list  # measured lots from the cycle before this PM
    past_pms: list  # earlier PMs on this chamber and what followed them
    matching: dict  # latest metrology tool-matching check
    truth: dict  # explanation, for review only
    hidden: dict = field(default_factory=dict)  # physics the tools must not read
    origin: dict | None = None  # the diagnosis that held this chamber, when there was one


def _rng(case_id: str, stream: str) -> np.random.Generator:
    return np.random.default_rng(zlib.crc32(f"{case_id}/{stream}".encode()))


def generate(scenario: str, seed: int, level: int = 0) -> RecoveryCase:
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r}")
    cid = f"rec_{scenario}-{seed}" if level == 0 else f"rec_{scenario}@L{level}-{seed}"
    nscale = NOISE_SCALE[level]
    rng = _rng(cid, "setup")
    chamber = sim.CHAMBERS[int(rng.integers(len(sim.CHAMBERS)))]
    pre_frac = float(rng.uniform(0.962, 0.975))  # rate just before PM, buildup lowered it
    shift = float(rng.uniform(0.006, 0.014)) * (1 if rng.random() < 0.5 else -1)
    post_frac = 1.0 + shift  # a clean chamber rarely comes back exactly at nominal
    season = 0.0
    drift = float(rng.uniform(0.04, 0.08))  # normal thinning per run as the walls coat again
    bias = {"MET01": float(rng.normal(0, 0.2)), "MET02": float(rng.normal(0, 0.2))}
    pm = {
        "chamber": chamber,
        "pm_id": f"PM-{int(rng.integers(300, 900))}",
        "work": "wet clean, wall buildup removed",
        "parts_replaced": [],
        "seasoning": "5 dummy wafers run after the clean",
        "duration_h": round(float(rng.uniform(5, 8)), 1),
    }
    truth = {"scenario": scenario}
    if scenario == "post_pm_reset":
        truth["explanation"] = "The clean removed the wall buildup, so the rate came back up; the pre-PM recipe runs thick."
    elif scenario == "seasoning":
        season = -float(rng.uniform(7, 11))
        pm["seasoning"] = "skipped, the tool was needed back early"
        truth["explanation"] = (
            f"Seasoning was skipped, so the first two wafers after PM came out about {abs(season):.1f} A thin. "
            "A recipe centered on those wafers overshoots thick."
        )
    elif scenario == "fast_drift":
        drift = float(rng.uniform(0.7, 1.0))
        pm["parts_replaced"] = ["showerhead (new)"]
        truth["explanation"] = (
            f"A new showerhead coats fast at first: film thins about {drift:.2f} A per lot. "
            "Plain EWMA on half the lots lags behind."
        )
    elif scenario == "metrology_bias":
        bias["MET02"] = float(rng.uniform(5.0, 7.0))
        truth["explanation"] = (
            f"MET02 reads about {bias['MET02']:.1f} A high. Centering the recipe on MET02 monitor wafers runs thin."
        )
    elif scenario == "no_shift":
        post_frac = pre_frac + float(rng.normal(0, 0.0015))
        pm["work"] = "door O-ring replaced, chamber not opened to clean"
        pm["seasoning"] = "not needed"
        pm["duration_h"] = round(float(rng.uniform(1, 2)), 1)
        truth["explanation"] = "Nothing inside the chamber changed. The pre-PM recipe is still right."
    pre_time = round(TARGET / (pre_frac * R_NOM), 2)

    # history: measured lots from the last part of the previous cycle (buildup pulling the rate down)
    hist = []
    for k in range(18):
        lots_since_pm = 200 + 6 * k
        t = round(pre_time * (1 + 0.0006 * (18 - k)), 2)  # the controller has been stretching the time
        frac = pre_frac * (1 + 0.0006 * (18 - k))
        tool = sim.MET_TOOLS[int(rng.integers(2))]
        y = frac * R_NOM * t + rng.normal(0, LOT_NOISE * nscale) + bias[tool] + rng.normal(0, MET_NOISE * nscale)
        hist.append({"lots_since_last_pm": lots_since_pm, "recipe_time_s": t, "thickness_A": round(float(y), 2), "met_tool": tool})

    # earlier PMs on this chamber: one showerhead swap and one skipped seasoning, always present
    other_drift = float(rng.uniform(0.7, 1.0))
    other_season = float(rng.uniform(7, 11))
    past = [
        {
            "pm_id": f"PM-{int(rng.integers(100, 299))}",
            "work": "wet clean, showerhead replaced (new)",
            "seasoning": "5 dummy wafers run",
            "first_wafers_vs_later_A": round(float(rng.normal(-0.4, 0.3)), 2),
            "thickness_slope_A_per_lot_first_40": -round(drift if scenario == "fast_drift" else other_drift, 2),
        },
        {
            "pm_id": f"PM-{int(rng.integers(100, 299))}",
            "work": "wet clean",
            "seasoning": "skipped",
            "first_wafers_vs_later_A": -round(abs(season) if scenario == "seasoning" else other_season, 2),
            "thickness_slope_A_per_lot_first_40": -round(float(rng.uniform(0.04, 0.08)), 2),
        },
        {
            "pm_id": f"PM-{int(rng.integers(100, 299))}",
            "work": "wet clean",
            "seasoning": "5 dummy wafers run",
            "first_wafers_vs_later_A": round(float(rng.normal(-0.3, 0.3)), 2),
            "thickness_slope_A_per_lot_first_40": -round(float(rng.uniform(0.04, 0.08)), 2),
        },
    ]
    rng.shuffle(past)
    matching = {
        "reference_wafer_certified_A": 500.0,
        "MET01_reads_A": round(500.0 + bias["MET01"] + float(rng.normal(0, 0.15)), 2),
        "MET02_reads_A": round(500.0 + bias["MET02"] + float(rng.normal(0, 0.15)), 2),
        "checked_hours_ago": round(float(rng.uniform(2, 20)), 1),
    }
    hidden = {"post_frac": post_frac, "pre_frac": pre_frac, "season": season, "drift": drift, "bias": bias, "noise_scale": nscale}
    return RecoveryCase(cid, scenario, seed, chamber, pm, pre_time, hist, past, matching, truth, hidden)


def generate_linked(diag_id: str) -> RecoveryCase:
    """The recovery that follows a pm_shift diagnosis: same chamber, same PM, same shift.

    The diagnosis simulator models film offsets, this one models rate x time, so the PM shift
    seen in the diagnosis (about +15 A at the old recipe) becomes the rate change here.
    """
    diag = sim.load(diag_id)
    if diag.scenario != "pm_shift":
        raise ValueError("only pm_shift diagnoses lead to a recovery")
    chamber = diag.alarm["chamber"]
    pm_t, shift = diag.hidden["world"].chamber_step[chamber][-1]
    base = generate("post_pm_reset", 100 + diag.seed)
    cid = f"rec_after_{diag_id}"
    base.case_id, base.chamber = cid, chamber
    base.pm = {**base.pm, "chamber": chamber, "pm_id": f"PM at {pm_t} h"}
    base.hidden["post_frac"] = base.hidden["pre_frac"] * (1 + shift / TARGET)
    base.origin = {"case_id": diag_id, "alarm_id": diag.alarm["alarm_id"], "lot_id": diag.alarm["lot_id"]}
    base.truth = {
        "scenario": "post_pm_reset",
        "explanation": f"Same chamber and PM as alarm {diag.alarm['alarm_id']}: {chamber} came back from PM running "
        f"about {shift:.0f} A thick at the old recipe. A monitor wafer shows it; the recipe needs to come down.",
    }
    return base


_CACHE: dict = {}


def load(case_id: str) -> RecoveryCase:
    if case_id not in _CACHE:
        if case_id.startswith("rec_after_"):
            _CACHE[case_id] = generate_linked(case_id.removeprefix("rec_after_"))
        else:
            name, seed = case_id.removeprefix("rec_").rsplit("-", 1)
            scenario, _, level = name.partition("@L")
            _CACHE[case_id] = generate(scenario, int(seed), int(level or 0))
    return _CACHE[case_id]


def all_ids() -> list:
    return benchmark("all") + benchmark("linked")


# ---------------------------------------------------------------------------- physics


def true_thickness(case: RecoveryCase, time_s: float, run_index: int, noise: float) -> float:
    """Film on a wafer that is the `run_index`-th run after PM (1 = first)."""
    h = case.hidden
    season = h["season"] if run_index <= 2 else 0.0
    return h["post_frac"] * R_NOM * time_s + season - h["drift"] * (run_index - 1) + noise


def _monitor(case: RecoveryCase, time_s: float, run_index: int, met_tool: str) -> tuple:
    r = _rng(case.case_id, f"monitor/{run_index}")
    true = true_thickness(case, time_s, run_index, float(r.normal(0, 1.0 * case.hidden.get("noise_scale", 1.0))))
    measured = true + case.hidden["bias"][met_tool] + float(_rng(case.case_id, f"met/{run_index}/{met_tool}").normal(0, MET_NOISE * case.hidden.get("noise_scale", 1.0)))
    return true, measured


# ---------------------------------------------------------------------------- tools

DEFINITIONS = [
    {
        "name": "get_recovery_brief",
        "description": "The held chamber, its PM record (work done, parts replaced, seasoning), the recipe time before PM, the baseline recipe time, limits, the controller defaults and your monitor-wafer budget.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "get_chamber_history",
        "description": "Measured production lots from the end of the previous PM cycle, and earlier PMs on this chamber with what happened after each (first wafers vs later wafers, thickness slope per lot over the first 40 lots).",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "get_metrology_matching",
        "description": "The latest tool-matching check: both metrology tools measured a certified reference wafer.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "run_monitor_wafer",
        "description": "Run one monitor wafer on the held chamber at a recipe time and measure it. Costs 0.5 h of chamber time. At most 4 per recovery. Each wafer counts as a run since PM.",
        "parameters": {
            "type": "object",
            "properties": {
                "time_s": {"type": "number", "description": "deposition time in seconds"},
                "met_tool": {"type": "string", "enum": sim.MET_TOOLS, "description": "metrology tool; default MET02"},
            },
            "required": ["time_s"],
        },
    },
    {
        "name": "estimate_recipe",
        "description": "Estimate the deposition rate from monitor wafers you ran and the recipe time that hits 500 A. Pick which monitor results to use. Optionally correct a metrology tool's offset with a value taken from the matching check.",
        "parameters": {
            "type": "object",
            "properties": {
                "monitor_evidence_ids": {"type": "array", "items": {"type": "string"}},
                "met_offsets_A": {
                    "type": "object",
                    "description": "e.g. {\"MET02\": 4.21} means MET02 reads 4.21 A high; subtracted before estimating",
                    "additionalProperties": {"type": "number"},
                },
            },
            "required": ["monitor_evidence_ids"],
        },
    },
    {
        "name": "release_chamber",
        "description": "Set the recipe and controller and release the chamber to production. Runs the verifier; refused releases can be fixed and resubmitted (3 tries).",
        "parameters": {
            "type": "object",
            "properties": {
                "time_s": {"type": "number", "description": "recipe time to start production with; copy it from evidence"},
                "ewma_lambda": {"type": "number", "description": "EWMA weight on each new measurement, 0.1 to 0.6; default 0.3"},
                "drift_A_per_lot": {"type": "number", "description": "expected film thinning per lot for the controller to pre-compensate, as a positive number (a history slope of -0.8 A per lot means 0.8); 0 for none"},
                "claims": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"evidence_id": {"type": "string"}, "statement": {"type": "string"}},
                        "required": ["evidence_id", "statement"],
                    },
                },
                "summary": {"type": "string"},
            },
            "required": ["time_s", "claims", "summary"],
        },
    },
]

SYSTEM = """You are FabTriage in recovery mode. A CVD deposition chamber was held after preventive
maintenance (PM). Your job: bring it back to the 500 A film target and release it to production,
spending as little chamber time as you can and never sending out-of-spec film.

How this chamber works
- Film thickness = deposition rate x deposition time. Target 500 A, control limits 493 to 507 A,
  spec 485 to 515 A. The baseline recipe time for a clean chamber is 60 s.
- Before PM, wall buildup slowly lowered the rate and the run-to-run controller stretched the time.
  A wet clean removes the buildup, so the old recipe usually runs thick. A PM that did not open
  the chamber leaves the rate where it was.
- A clean chamber rarely comes back exactly at nominal; only a monitor wafer tells you where it is.
- Without seasoning wafers after a clean, the first wafers can come out thin. They don't show
  where the chamber will settle.
- New parts can coat quickly at first, so film thins lot by lot for a while.
- Metrology tools can be offset from each other; the matching check shows by how much.
- After release an EWMA controller keeps adjusting the time from the measured lots (about half).
  You set its starting time, its weight (ewma_lambda) and an optional drift pre-compensation
  (drift_A_per_lot, the thinning you expect per lot).

What things cost
- Each monitor wafer costs 0.5 h of chamber time; at most 4.
- Off-target lots after release are the main cost. Out-of-spec lots are the worst outcome.
- Changing the recipe from noise also costs: don't change what isn't broken.

How to work
- Start with get_recovery_brief. Decide what could make this recovery go wrong and check that.
- Call exactly one tool per turn. Plain text without a tool call is not accepted.
- Get recipe numbers from estimate_recipe (or keep the pre-PM or baseline time); don't compute them yourself.
- In release_chamber each claim cites one evidence_id, and every number in it is copied from that
  evidence. The verifier refuses a release after a chamber clean or a part change unless a monitor
  wafer confirmed the rate, and caps one recipe change at 8% of the pre-PM time.
- Write claims and the summary in plain words an engineer can check in seconds.
"""


class RecoveryJob:
    """Same interface as tools.Investigation, so the agent loop can drive it."""

    DEFINITIONS = DEFINITIONS
    SYSTEM = SYSTEM
    FINAL_TOOL = "release_chamber"

    def __init__(self, case: RecoveryCase, run_dir: Path | None = None):
        self.case = case
        self.run_dir = Path(run_dir) if run_dir else None
        self.evidence: dict = {}
        self.trace: list = []
        self.monitors: list = []  # {"evidence_id", "time_s", "met_tool", "run_index", "measured", "true"}
        self.tries = 0
        self.status = "running"
        self.release: dict | None = None
        self.refusals: list = []
        self.verify_enabled = True
        self.posthoc_problems: list = []
        self.notes: list = []
        self.autosave = False
        self.live_extra: dict = {}
        self.hide: set = set()  # ablation: "history" drops earlier PMs, "pm_detail" drops parts and seasoning

    def kickoff(self, engineer_note=None) -> str:
        return f"{self.case.chamber} is on hold after {self.case.pm['pm_id']}. Recover it and release it to production."

    def call(self, name: str, args: dict) -> dict:
        args = args or {}
        if self.status != "running":
            return {"error": f"recovery is closed ({self.status})"}
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
        if name != "release_chamber" and "error" not in result:
            eid = f"E{len(self.evidence) + 1}"
            result = {"evidence_id": eid, **result}
            self.evidence[eid] = {"tool": name, "args": args, "result": result}
            if name == "run_monitor_wafer":
                self.monitors[-1]["evidence_id"] = eid
        self.trace.append({"tool": name, "args": args, "result": result})
        if self.autosave:
            self.save(self.live_extra)
        return result

    def costs(self) -> dict:
        down = MONITOR_DOWNTIME_H * len(self.monitors) + (ENGINEER_FALLBACK_H if self.status == "needs_engineer" else 0)
        return {
            "tool_calls": len(self.trace),
            "monitor_wafers": len(self.monitors),
            "downtime_h": round(down, 2),
            "release_tries": self.tries,
        }

    # ------------------------------------------------------------------ tools
    def t_get_recovery_brief(self):
        c = self.case
        pm = c.pm
        if "pm_detail" in self.hide:
            pm = {"chamber": pm["chamber"], "pm_id": pm["pm_id"], "work": "PM completed (details not recorded)", "duration_h": pm["duration_h"]}
        return {
            "chamber": c.chamber,
            "pm_record": pm,
            "pre_pm_recipe_time_s": c.pre_pm_time_s,
            "baseline_recipe_time_s_clean_chamber": T_NOM,
            "target_A": TARGET,
            "control_limits_A": [sim.LCL, sim.UCL],
            "spec_limits_A": [sim.LSL, sim.USL],
            "controller": {"type": "EWMA on deposition rate", "default_lambda": DEFAULT_LAMBDA, "measured_lot_fraction": 0.5},
            "monitor_wafers_left": MAX_MONITORS - len(self.monitors),
            "default_monitor_metrology_tool": DEFAULT_MONITOR_TOOL,
            **({"held_after": f"alarm {c.origin['alarm_id']}: diagnosed as a chamber shift after this PM"} if c.origin else {}),
        }

    def t_get_chamber_history(self):
        h = self.case.history
        out = {
            "chamber": self.case.chamber,
            "end_of_previous_cycle": h,
            "mean_thickness_last_10_A": round(float(np.mean([x["thickness_A"] for x in h[-10:]])), 2),
            "earlier_pms": self.case.past_pms,
        }
        if "history" in self.hide:
            out["earlier_pms"] = "not available"
        return out

    def t_get_metrology_matching(self):
        m = dict(self.case.matching)
        m["MET02_minus_MET01_A"] = round(m["MET02_reads_A"] - m["MET01_reads_A"], 2)
        return m

    def t_run_monitor_wafer(self, time_s, met_tool=DEFAULT_MONITOR_TOOL):
        if len(self.monitors) >= MAX_MONITORS:
            raise ValueError(f"monitor budget used up ({MAX_MONITORS})")
        if met_tool not in sim.MET_TOOLS:
            raise ValueError(f"unknown metrology tool {met_tool!r}")
        time_s = float(time_s)
        if not 40 <= time_s <= 80:
            raise ValueError("time_s must be between 40 and 80")
        idx = len(self.monitors) + 1
        true, measured = _monitor(self.case, time_s, idx, met_tool)
        self.monitors.append({"time_s": time_s, "met_tool": met_tool, "run_index": idx, "measured": measured, "true": true})
        return {
            "wafer": f"monitor {idx}",
            "runs_since_pm": idx,
            "time_s": round(time_s, 2),
            "met_tool": met_tool,
            "thickness_A": round(measured, 2),
            "implied_rate_A_per_s": round(measured / time_s, 4),
            "monitor_wafers_left": MAX_MONITORS - idx,
        }

    def t_estimate_recipe(self, monitor_evidence_ids, met_offsets_A=None):
        offsets = {k: float(v) for k, v in (met_offsets_A or {}).items()}
        for tool, value in offsets.items():
            if tool not in sim.MET_TOOLS:
                raise ValueError(f"unknown metrology tool {tool!r}")
            if not any(e["tool"] == "get_metrology_matching" for e in self.evidence.values()):
                raise ValueError("offsets must come from the matching check; call get_metrology_matching first")
            pool = [n for e in self.evidence.values() if e["tool"] == "get_metrology_matching" for n in verify.evidence_numbers(e["result"])]
            if not any(abs(abs(value) - abs(p - 500.0)) < 0.011 or abs(abs(value) - abs(p)) < 0.011 for p in pool):
                raise ValueError(f"offset {value} for {tool} does not match the matching check")
        used = []
        for eid in monitor_evidence_ids:
            m = next((m for m in self.monitors if m.get("evidence_id") == eid), None)
            if m is None:
                raise ValueError(f"{eid} is not a monitor wafer result")
            used.append(m)
        if not used:
            raise ValueError("give at least one monitor wafer evidence id")
        rates = [(round(m["measured"], 2) - offsets.get(m["met_tool"], 0.0)) / m["time_s"] for m in used]
        rate = float(np.mean(rates))
        time_s = TARGET / rate
        return {
            "monitors_used": [f"monitor {m['run_index']}" for m in used],
            "offsets_applied_A": offsets,
            "rate_A_per_s": round(rate, 4),
            "recipe_time_s_for_500A": round(time_s, 2),
            "change_vs_pre_pm_pct": round((time_s / self.case.pre_pm_time_s - 1) * 100, 2),
            "pre_pm_time_would_give_A": round(rate * self.case.pre_pm_time_s, 2),
        }

    def t_release_chamber(self, time_s, claims, summary, ewma_lambda=DEFAULT_LAMBDA, drift_A_per_lot=0.0):
        self.tries += 1
        release = {
            "time_s": float(time_s),
            "ewma_lambda": float(ewma_lambda),
            "drift_A_per_lot": float(drift_A_per_lot or 0.0),
            "claims": claims,
            "summary": summary,
        }
        problems = check(self, release)
        if not self.verify_enabled:
            self.posthoc_problems = problems
            problems = []
        if not problems:
            self.release = release
            self.status = "released"
            return {"accepted": True, "status": "released", "note": "Chamber released to production."}
        self.refusals.append({"try": self.tries, "problems": problems, "release": release})
        if self.tries >= MAX_TRIES:
            self.release = release
            self.status = "needs_engineer"
            return {"accepted": False, "status": "needs_engineer", "problems": problems}
        return {"accepted": False, "problems": problems, "tries_left": MAX_TRIES - self.tries}

    # ------------------------------------------------------------------ saving
    def save(self, extra: dict | None = None) -> Path | None:
        if self.run_dir is None:
            return None
        self.run_dir.mkdir(parents=True, exist_ok=True)
        path = self.run_dir / "run.json"
        c = self.case
        data = {
            "case_id": c.case_id,
            "chamber": c.chamber,
            "pm": c.pm,
            "pre_pm_time_s": c.pre_pm_time_s,
            "status": self.status,
            "release": self.release,
            "refusals": self.refusals,
            "verifier_enabled": self.verify_enabled,
            "posthoc_problems": self.posthoc_problems,
            "costs": self.costs(),
            "trace": self.trace,
            "notes": self.notes,
            "truth": c.truth,
            **(extra or {}),
        }
        path.write_text(json.dumps(data, indent=2, default=str))
        return path


# ---------------------------------------------------------------------------- verifier


def check(job: RecoveryJob, r: dict) -> list:
    c = job.case
    problems = []
    claims = [x for x in r.get("claims") or [] if isinstance(x, dict)]
    if len(claims) < 2:
        problems.append("rule: give at least two claims, each citing the evidence it rests on")
    cited = set()
    for i, cl in enumerate(claims, 1):
        eid, text = str(cl.get("evidence_id", "")), str(cl.get("statement", ""))
        if eid not in job.evidence:
            problems.append(f"claim {i}: evidence {eid!r} does not exist")
            continue
        cited.add(eid)
        pool = verify.evidence_numbers(job.evidence[eid]["result"]) + [T_NOM]
        missing = [n for n in verify.numbers_in(text) if not verify.grounded(n, pool)]
        if missing:
            problems.append(f"claim {i}: number(s) {', '.join(missing)} do not appear in {eid}; copy numbers exactly from the evidence")
    if len(claims) >= 2 and len(cited) < 2:
        problems.append("rule: cite at least two different pieces of evidence")

    t = r["time_s"]
    allowed = [c.pre_pm_time_s, T_NOM] + [
        e["result"]["recipe_time_s_for_500A"] for e in job.evidence.values() if e["tool"] == "estimate_recipe"
    ]
    if not any(abs(t - a) < 0.011 for a in allowed):
        problems.append(
            f"rule: time_s {t} is not from evidence; use the pre-PM time, the baseline time or a recipe_time_s_for_500A from estimate_recipe"
        )
    if abs(t / c.pre_pm_time_s - 1) > MAX_CHANGE + 1e-9:
        problems.append(f"rule: one recipe change is capped at 8% of the pre-PM time {c.pre_pm_time_s} s")
    opened = "clean" in c.pm["work"] and "not opened" not in c.pm["work"] or bool(c.pm["parts_replaced"])
    if "pm_detail" in job.hide:
        opened = True  # what was done is unknown, so the playbook asks for a monitor wafer
    if opened and not job.monitors:
        problems.append("rule: after a chamber clean, a part change or an unrecorded PM, run at least one monitor wafer before release")
    lam = r["ewma_lambda"]
    if not 0.1 <= lam <= 0.6:
        problems.append("rule: ewma_lambda must be between 0.1 and 0.6")
    d = r["drift_A_per_lot"]
    if d < 0:
        problems.append(
            f"rule: drift_A_per_lot is the thinning per lot as a positive number; {d} would push the film the wrong way "
            f"(a thickness slope of {d} A per lot means drift_A_per_lot {abs(d)})"
        )
    if d:
        if abs(d) > 1.5:
            problems.append("rule: drift_A_per_lot above 1.5 A per lot is not credible")
        pool = [n for e in job.evidence.values() for n in verify.evidence_numbers(e["result"])]
        if not verify.grounded(f"{abs(d)}", [abs(p) for p in pool]):
            problems.append(f"rule: drift_A_per_lot {d} is not from evidence")
    return problems


# ---------------------------------------------------------------------------- what happens next


def run_out(case: RecoveryCase, time_s: float, ewma_lambda: float, drift_ctrl: float, n_monitors: int) -> dict:
    """Run 40 production lots under the EWMA controller, starting from the released recipe."""
    r = _rng(case.case_id, "production")
    k = case.hidden.get("noise_scale", 1.0)
    lot_noise = r.normal(0, LOT_NOISE * k, N_LOTS)
    met_noise = r.normal(0, MET_NOISE * k, N_LOTS)
    measured = r.random(N_LOTS) < sim.MEASURE_PROB
    tools = r.integers(0, 2, N_LOTS)
    a = TARGET / time_s  # controller's rate estimate
    lots = []
    for k in range(N_LOTS):
        t = TARGET / a
        idx = n_monitors + k + 1
        true = true_thickness(case, t, idx, float(lot_noise[k]))
        row = {"lot": k + 1, "time_s": round(t, 3), "true_A": round(true, 2), "measured_A": None}
        if measured[k]:
            tool = sim.MET_TOOLS[int(tools[k])]
            y = true + case.hidden["bias"][tool] + float(met_noise[k])
            row["measured_A"], row["met_tool"] = round(y, 2), tool
            a = ewma_lambda * (y / t) + (1 - ewma_lambda) * a
        a -= drift_ctrl / t  # expected thinning, pre-compensated
        lots.append(row)
    err = np.array([x["true_A"] - TARGET for x in lots])
    return {
        "lots": lots,
        "off_target_lots": int(np.sum(np.abs(err) > sim.UCL - TARGET)),
        "out_of_spec_lots": int(np.sum(np.abs(err) > sim.USL - TARGET)),
        "mean_abs_error_A": round(float(np.mean(np.abs(err))), 2),
        "first_5_mean_error_A": round(float(np.mean(err[:5])), 2),
    }


def score(job: RecoveryJob) -> dict:
    c = job.case
    if job.status == "released":
        rel = job.release
        out = run_out(c, rel["time_s"], rel["ewma_lambda"], rel["drift_A_per_lot"], len(job.monitors))
        change = (rel["time_s"] / c.pre_pm_time_s - 1) * 100
    else:  # refused or never released: an engineer takes over with the two-monitor guide rule
        fallback = RecoveryJob(c)
        monitor_rule(fallback)
        rel = fallback.release
        out = run_out(c, rel["time_s"], rel["ewma_lambda"], rel["drift_A_per_lot"], len(job.monitors) + 2)
        change = (rel["time_s"] / c.pre_pm_time_s - 1) * 100
    costs = job.costs()
    if job.status != "released":
        costs["downtime_h"] = round(costs["downtime_h"] + 2 * MONITOR_DOWNTIME_H, 2)
    row = {
        "case_id": c.case_id,
        "status": job.status,
        "off_target_lots": out["off_target_lots"] if out else None,
        "out_of_spec_lots": out["out_of_spec_lots"] if out else None,
        "mean_abs_error_A": out["mean_abs_error_A"] if out else None,
        "first_5_mean_error_A": out["first_5_mean_error_A"] if out else None,
        "monitor_wafers": costs["monitor_wafers"],
        "downtime_h": costs["downtime_h"],
        "recipe_change_pct": round(change, 2) if change is not None else None,
        "rule_broken": bool(job.posthoc_problems) or bool(job.refusals and job.status != "released"),
        "tool_calls": costs["tool_calls"],
    }
    return row, out


# ---------------------------------------------------------------------------- fixed rules


def _brief_claims(job):
    b = next(e for e, v in job.evidence.items() if v["tool"] == "get_recovery_brief")
    h = job.call("get_chamber_history", {})["evidence_id"]
    return [
        {"evidence_id": b, "statement": f"Pre-PM recipe time {job.case.pre_pm_time_s} s, baseline {T_NOM} s."},
        {"evidence_id": h, "statement": "Previous cycle read."},
    ]


def keep_recipe(job: RecoveryJob):
    """Status quo: release with the pre-PM recipe and let EWMA catch up."""
    job.verify_enabled = False
    job.call("get_recovery_brief", {})
    job.call("release_chamber", {"time_s": job.case.pre_pm_time_s, "claims": _brief_claims(job), "summary": "Keep the recipe; the controller adapts."})


def reset_recipe(job: RecoveryJob):
    """Guide rule: after PM go back to the baseline recipe."""
    job.verify_enabled = False
    job.call("get_recovery_brief", {})
    t = T_NOM if abs(T_NOM / job.case.pre_pm_time_s - 1) <= MAX_CHANGE else job.case.pre_pm_time_s
    job.call("release_chamber", {"time_s": t, "claims": _brief_claims(job), "summary": "Baseline recipe after PM."})


def monitor_rule(job: RecoveryJob):
    """Guide rule: two monitor wafers on the default tool at the pre-PM time, re-center on their mean."""
    job.call("get_recovery_brief", {})
    ids = []
    for _ in range(2):
        ids.append(job.call("run_monitor_wafer", {"time_s": job.case.pre_pm_time_s})["evidence_id"])
    est = job.call("estimate_recipe", {"monitor_evidence_ids": ids})
    t = est["recipe_time_s_for_500A"]
    lo, hi = job.case.pre_pm_time_s * (1 - MAX_CHANGE), job.case.pre_pm_time_s * (1 + MAX_CHANGE)
    if not lo <= t <= hi:
        t = job.case.pre_pm_time_s
    job.call(
        "release_chamber",
        {
            "time_s": t,
            "claims": [
                {"evidence_id": est["evidence_id"], "statement": f"Two monitor wafers give {est['recipe_time_s_for_500A']} s for 500 A."},
                {"evidence_id": ids[0], "statement": "Monitor wafer measured after PM."},
            ],
            "summary": "Re-centered on two monitor wafers.",
        },
    )


def oracle(job: RecoveryJob):
    """Not a method: it reads the hidden truth and sets the perfect recipe and drift term.
    What is left over is the noise floor, the off-target lots nobody could avoid."""
    job.verify_enabled = False
    h = job.case.hidden
    job.call("get_recovery_brief", {})
    t = TARGET / (h["post_frac"] * R_NOM)
    job.call(
        "release_chamber",
        {"time_s": round(t, 2), "drift_A_per_lot": round(h["drift"], 3), "claims": _brief_claims(job), "summary": "oracle"},
    )


BASELINES = {"keep_recipe": keep_recipe, "reset_recipe": reset_recipe, "monitor_rule": monitor_rule, "oracle": oracle}
METHODS = ["agent", "monitor_rule", "reset_recipe", "keep_recipe"]
