"""A small virtual fab: one CVD deposition step and the steps around it.

Route per lot: CLEAN (CLN01, CLN02) -> DEP (4 chambers on 2 tools) -> MET (MET01, MET02).
About half of the lots get one wafer measured at 49 sites. Every DEP run logs four FDC
sensor values. Chambers drift as material builds up inside them, PM resets the buildup,
and run-to-run compensation keeps most of that drift in check.

A Case is the fab history up to the moment an alarm fires, plus the hidden truth about
what caused it. Tools only ever read `Case.lots`, `Case.pm_log` and `Case.alarm`;
the truth and the generation parameters stay in `Case.truth` and `Case.hidden`.
"""

from __future__ import annotations

import math
import zlib
from dataclasses import dataclass, field

import numpy as np

TARGET = 500.0  # film thickness target, angstrom
LSL, USL = 485.0, 515.0  # spec limits
LCL, UCL = 493.0, 507.0  # SPC control limits on the wafer mean
CHAMBERS = ["DEP01-A", "DEP01-B", "DEP02-A", "DEP02-B"]
CLEAN_TOOLS = ["CLN01", "CLN02"]
MET_TOOLS = ["MET01", "MET02"]
FDC_PARAMS = {  # nominal value, run-to-run noise
    "heater_temp_C": (400.0, 0.4),
    "rf_power_W": (300.0, 0.8),
    "pressure_Torr": (2.0, 0.008),
    "gas_flow_sccm": (100.0, 0.4),
}
WAFERS_PER_LOT = 25
HISTORY_HOURS = 72.0
LOT_INTERVAL_H = 0.3
MEASURE_PROB = 0.5
REMEASURE_DELAY_H = 1.5


def site_positions() -> np.ndarray:
    """49 measurement sites: center plus rings of 8, 16 and 24 (radius normalized to 1)."""
    pts = [(0.0, 0.0)]
    for n, r in ((8, 0.33), (16, 0.66), (24, 0.95)):
        for k in range(n):
            a = 2 * math.pi * k / n
            pts.append((r * math.cos(a), r * math.sin(a)))
    return np.array(pts)


SITES = site_positions()
RADIUS = np.hypot(SITES[:, 0], SITES[:, 1])
R4_MEAN = float(np.mean(RADIUS**4))
R2_MEAN = float(np.mean(1 - RADIUS**2))


@dataclass
class Case:
    case_id: str
    scenario: str
    seed: int
    lots: list  # dicts, oldest first; the alarm lot is last
    pm_log: list  # {"chamber", "time_h"}
    alarm: dict
    truth: dict
    hidden: dict = field(default_factory=dict)  # generation state the tools must not read
    now_h: float = HISTORY_HOURS

    def lot(self, lot_id: str) -> dict:
        for lot in self.lots:
            if lot["lot_id"] == lot_id:
                return lot
        raise KeyError(f"unknown lot: {lot_id}")


class _World:
    """Generates the history. Scenario functions tweak its knobs before `run()`."""

    def __init__(self, rng: np.random.Generator):
        self.rng = rng
        self.offset = {c: rng.normal(0, 1.2) for c in CHAMBERS}
        self.drift = {c: max(0.05, rng.normal(0.25, 0.08)) for c in CHAMBERS}  # A per 100 wafers
        self.since_pm = {c: int(rng.integers(0, 500)) for c in CHAMBERS}
        self.pm_times = {c: self._pm_schedule() for c in CHAMBERS}
        self.edge_bias = {c: -1.5 for c in CHAMBERS}
        # scenario knobs: each is a list of (start_h, end_h, value) or similar
        self.chamber_step = {c: [] for c in CHAMBERS}  # (start, mean shift)
        self.clean_shift = {t: [] for t in CLEAN_TOOLS}  # (start, center-thick shift)
        self.met_shift = {t: [] for t in MET_TOOLS}  # (start, end, offset)
        self.fdc_step = {c: [] for c in CHAMBERS}  # (start, param, delta, physical: bool)
        self.edge_growth = {c: 0.0 for c in CHAMBERS}  # extra edge buildup per 100 wafers
        self.forced_last = {}  # alarm lot routing

    def _pm_schedule(self) -> list:
        t, times = float(self.rng.uniform(-30, 20)), []
        while t < HISTORY_HOURS - 1:
            if t > 0:
                times.append(round(t, 2))
            t += float(self.rng.uniform(30, 42))
        return times

    def run(self) -> tuple:
        lots, pm_log = [], []
        n = int(HISTORY_HOURS / LOT_INTERVAL_H)
        next_pm = {c: list(self.pm_times[c]) for c in CHAMBERS}
        last_pm = {c: None for c in CHAMBERS}
        for i in range(n):
            t = round((i + 1) * LOT_INTERVAL_H, 2)
            last = i == n - 1
            for c in CHAMBERS:
                while next_pm[c] and next_pm[c][0] <= t:
                    pm_t = next_pm[c].pop(0)
                    pm_log.append({"chamber": c, "time_h": pm_t})
                    self.since_pm[c] = 0
                    last_pm[c] = pm_t
            route = self.forced_last if last else {}
            clean = route.get("clean") or CLEAN_TOOLS[int(self.rng.integers(2))]
            chamber = route.get("chamber") or CHAMBERS[int(self.rng.integers(4))]
            met = route.get("met") or MET_TOOLS[int(self.rng.integers(2))]
            measured = route.get("measured", True) if last else self.rng.random() < MEASURE_PROB
            lot_id = f"LOT-{1000 + i}"
            slot = int(self.rng.integers(1, WAFERS_PER_LOT + 1))
            true_sites, fdc = self._process(t, clean, chamber, last_pm[chamber], last and route.get("spot"))
            self.since_pm[chamber] += WAFERS_PER_LOT
            lot = {
                "lot_id": lot_id,
                "time_h": t,
                "clean_tool": clean,
                "chamber": chamber,
                "met_tool": met,
                "wafer_id": f"{lot_id}-W{slot:02d}",
                "fdc": fdc,
                "wafers_since_pm": self.since_pm[chamber],
                "_true_sites": true_sites,  # hidden: what the wafer really looks like
                "measurement": None,
            }
            if measured:
                lot["measurement"] = measure(true_sites, met, t, self, self.rng)
            lots.append(lot)
        return lots, sorted(pm_log, key=lambda p: p["time_h"])

    def _process(self, t, clean, chamber, last_pm, spot):
        rng = self.rng
        mean = TARGET + self.offset[chamber] + self.drift[chamber] * self.since_pm[chamber] / 100
        if last_pm is not None and 0 <= t - last_pm < 1.0:
            mean -= 1.5  # first lots after PM run slightly thin while the chamber seasons
        for start, shift in self.chamber_step[chamber]:
            if t >= start:
                mean += shift
        center = 0.0
        for start, shift in self.clean_shift[clean]:
            if t >= start:
                center += shift
        fdc = {}
        for p, (nominal, sd) in FDC_PARAMS.items():
            fdc[p] = nominal + rng.normal(0, sd)
        # run-to-run noise in the actual temperature, felt by the film
        mean += 0.8 * (fdc["heater_temp_C"] - FDC_PARAMS["heater_temp_C"][0]) * 0.3
        for start, p, delta, physical in self.fdc_step[chamber]:
            if t >= start:
                fdc[p] += delta  # what the sensor reports
                if physical and p == "heater_temp_C":
                    mean += 0.8 * delta  # a real temperature change moves the deposition rate
        mean += rng.normal(0, 1.2)
        if spot:
            mean += spot[3]  # a one-off wafer excursion
        edge = self.edge_bias[chamber] + self.edge_growth[chamber] * self.since_pm[chamber] / 100
        sites = (
            mean
            + edge * (RADIUS**4 - R4_MEAN)
            + center * (1 + 1.5 * ((1 - RADIUS**2) - R2_MEAN))
            + rng.normal(0, 1.0, len(SITES))
        )
        if spot:
            x0, y0, amp, _ = spot
            d2 = (SITES[:, 0] - x0) ** 2 + (SITES[:, 1] - y0) ** 2
            sites = sites + amp * np.exp(-d2 / (2 * 0.12**2))
        fdc = {k: round(float(v), 3) for k, v in fdc.items()}
        return [round(float(v), 2) for v in sites], fdc


def measure(true_sites, met_tool, t, world, rng) -> dict:
    """One metrology reading of a wafer: the true sites plus tool offset and noise."""
    offset = 0.3 if met_tool == "MET02" else 0.0
    for start, end, shift in world.met_shift[met_tool]:
        if start <= t <= end:
            offset += shift
    sites = np.array(true_sites) + offset + rng.normal(0, 0.4, len(true_sites))
    return {
        "met_tool": met_tool,
        "time_h": round(float(t), 2),
        "sites": [round(float(v), 2) for v in sites],
        "mean": round(float(sites.mean()), 2),
        "range": round(float(sites.max() - sites.min()), 2),
    }


# ---------------------------------------------------------------- scenarios

SCENARIOS = [
    "pm_shift",
    "buildup_drift",
    "metrology_error",
    "upstream_clean",
    "wafer_noise",
    "sensor_fault",
    "heater_drift",
]


def _pick(rng, items):
    return items[int(rng.integers(len(items)))]


def generate(scenario: str, seed: int) -> Case:
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario}")
    rng = np.random.default_rng(10_000 * (SCENARIOS.index(scenario) + 1) + seed)
    w = _World(rng)
    x = _pick(rng, CHAMBERS)
    others = [c for c in CHAMBERS if c != x]
    confound = bool(rng.random() < 0.5)
    T = HISTORY_HOURS
    hidden = {"chamber": x, "confounder": None}
    route = {"chamber": x}

    if scenario == "pm_shift":
        pm_t = round(T - rng.uniform(3, 9), 2)
        w.pm_times[x] = [p for p in w.pm_times[x] if p < pm_t - 20] + [pm_t]
        shift = float(rng.uniform(13, 19))
        w.chamber_step[x].append((pm_t, shift))
        if rng.random() < 0.5:  # sometimes FDC shows a hint: heater runs a bit hot after PM
            w.fdc_step[x].append((pm_t, "heater_temp_C", float(rng.uniform(2.0, 3.5)), False))
            hidden["fdc_hint"] = True
        if confound:
            route["met"] = "MET02"
            hidden["confounder"] = "alarm wafer happened to be measured on MET02"
        truth = {
            "cause": "chamber",
            "real_fault": True,
            "required": [["hold_lot", "ALARM_LOT"], ["hold_chamber", x]],
            "forbidden": ["release_lot"],
            "explanation": f"{x} came back from PM at {pm_t}h running about {shift:.0f} A thick.",
        }

    elif scenario == "buildup_drift":
        w.pm_times[x] = []
        w.since_pm[x] = int(rng.integers(900, 1300))
        lots_on_x = HISTORY_HOURS / LOT_INTERVAL_H / 4
        end_wafers = w.since_pm[x] + lots_on_x * WAFERS_PER_LOT
        target_mean = float(rng.uniform(514.5, 517.5))
        w.drift[x] = (target_mean - TARGET - w.offset[x]) / (end_wafers / 100)
        w.edge_growth[x] = float(rng.uniform(0.5, 0.8))
        if confound:
            route["clean"] = "CLN02"
            route["met"] = "MET02"
            hidden["confounder"] = "alarm lot went through CLN02 and MET02"
        truth = {
            "cause": "chamber",
            "real_fault": True,
            "required": [["hold_lot", "ALARM_LOT"], ["hold_chamber", x]],
            "forbidden": ["release_lot"],
            "explanation": f"{x} is overdue for PM; buildup has pushed deposition up, thickest at the edge.",
        }

    elif scenario == "metrology_error":
        persistent = bool(rng.random() < 0.6)
        shift = float(rng.uniform(17, 23))
        start = round(T - (rng.uniform(2.5, 5) if persistent else 0.05), 2)
        w.met_shift["MET02"].append((start, T + 0.01, shift))
        route["met"] = "MET02"
        hidden["persistent"] = persistent
        if persistent:
            # keep MET02 offset for remeasures too
            w.met_shift["MET02"][-1] = (start, T + 24, shift)
        if confound:
            pm_t = round(T - rng.uniform(2, 6), 2)
            w.pm_times[x] = [p for p in w.pm_times[x] if p < pm_t - 20] + [pm_t]
            hidden["confounder"] = f"{x} had a routine PM at {pm_t}h"
        truth = {
            "cause": "metrology",
            "real_fault": False,
            "required": [["release_lot", "ALARM_LOT"]],
            "forbidden": ["hold_chamber"],
            "needs_remeasure": True,
            "explanation": "MET02 read high" + (" for the last few hours." if persistent else " on this one reading."),
        }

    elif scenario == "upstream_clean":
        start = round(T - rng.uniform(3, 7), 2)
        w.clean_shift["CLN02"].append((start, float(rng.uniform(16, 21))))
        route["clean"] = "CLN02"
        if confound:
            pm_t = round(T - rng.uniform(2, 6), 2)
            w.pm_times[x] = [p for p in w.pm_times[x] if p < pm_t - 20] + [pm_t]
            hidden["confounder"] = f"{x} had a routine PM at {pm_t}h"
        truth = {
            "cause": "upstream",
            "real_fault": True,
            "required": [["hold_lot", "ALARM_LOT"], ["escalate_upstream", "CLN02"]],
            "forbidden": ["hold_chamber", "release_lot"],
            "explanation": "CLN02 started leaving the surface in a state that deposits thick in the center, on every chamber.",
        }

    elif scenario == "wafer_noise":
        a = rng.uniform(0, 2 * math.pi)
        r = rng.uniform(0.3, 0.7)
        route["spot"] = (r * math.cos(a), r * math.sin(a), float(rng.uniform(15, 25)), float(rng.uniform(8, 11)))
        if confound:
            route["met"] = "MET02"
            hidden["confounder"] = "alarm wafer measured on MET02"
        truth = {
            "cause": "noise",
            "real_fault": False,
            "required": [["release_lot", "ALARM_LOT"]],
            "forbidden": ["hold_chamber", "hold_lot"],
            "explanation": "One wafer has a local thick spot; the chamber and the rest of the lot history are normal.",
        }

    elif scenario == "sensor_fault":
        start = round(T - rng.uniform(1.5, 3.5), 2)
        w.fdc_step[x].append((start, "heater_temp_C", float(rng.uniform(10, 15)), False))
        route["measured"] = False
        if confound:
            pm_t = round(T - rng.uniform(4, 8), 2)
            w.pm_times[x] = [p for p in w.pm_times[x] if p < pm_t - 20] + [pm_t]
            hidden["confounder"] = f"{x} had a routine PM at {pm_t}h"
        truth = {
            "cause": "sensor",
            "real_fault": False,
            "required": [["flag_sensor", f"{x}:heater_temp_C"], ["release_lot", "ALARM_LOT"]],
            "forbidden": ["hold_chamber", "hold_lot"],
            "explanation": f"The heater temperature sensor on {x} reads high, but the film is normal.",
        }

    elif scenario == "heater_drift":
        start = round(T - rng.uniform(1.5, 3.5), 2)
        w.fdc_step[x].append((start, "heater_temp_C", float(rng.uniform(10, 14)), True))
        route["measured"] = False
        if confound:
            pm_t = round(T - rng.uniform(4, 8), 2)
            w.pm_times[x] = [p for p in w.pm_times[x] if p < pm_t - 20] + [pm_t]
            hidden["confounder"] = f"{x} had a routine PM at {pm_t}h"
        truth = {
            "cause": "chamber",
            "real_fault": True,
            "required": [["hold_lot", "ALARM_LOT"], ["hold_chamber", x]],
            "forbidden": ["release_lot"],
            "explanation": f"The heater on {x} really is running hot; films since then are thick.",
        }

    w.forced_last = route
    lots, pm_log = w.run()
    alarm_lot = lots[-1]
    hidden["world"] = w
    if scenario in ("sensor_fault", "heater_drift"):
        alarm = {
            "alarm_id": f"ALM-{zlib.crc32(f'{scenario}{seed}'.encode()) % 100000:05d}",
            "type": "FDC",
            "rule": "heater_temp_C above 403.0 (3 sigma)",
            "chamber": x,
            "parameter": "heater_temp_C",
            "value": alarm_lot["fdc"]["heater_temp_C"],
            "lot_id": alarm_lot["lot_id"],
            "time_h": alarm_lot["time_h"],
        }
    else:
        m = alarm_lot["measurement"]
        kind = "OOS" if (m["mean"] > USL or m["mean"] < LSL) else "OOC"
        alarm = {
            "alarm_id": f"ALM-{zlib.crc32(f'{scenario}{seed}'.encode()) % 100000:05d}",
            "type": kind,
            "rule": f"wafer mean outside {'spec ' + str(LSL) + '-' + str(USL) if kind == 'OOS' else 'control limits ' + str(LCL) + '-' + str(UCL)}",
            "chamber": x,
            "lot_id": alarm_lot["lot_id"],
            "wafer_id": alarm_lot["wafer_id"],
            "met_tool": m["met_tool"],
            "value": m["mean"],
            "time_h": alarm_lot["time_h"],
        }
    truth = dict(truth)
    truth["required"] = [[a, alarm_lot["lot_id"] if t == "ALARM_LOT" else t] for a, t in truth["required"]]
    truth["confounder"] = hidden["confounder"]
    return Case(
        case_id=f"{scenario}-{seed}",
        scenario=scenario,
        seed=seed,
        lots=lots,
        pm_log=pm_log,
        alarm=alarm,
        truth=truth,
        hidden=hidden,
    )


def remeasure(case: Case, lot_id: str, met_tool: str, n_previous: int) -> dict:
    """A new reading of a lot's sampled wafer, taken REMEASURE_DELAY_H after now."""
    lot = case.lot(lot_id)
    t = case.now_h + REMEASURE_DELAY_H * (n_previous + 1)
    rng = np.random.default_rng(zlib.crc32(f"{case.case_id}|{lot_id}|{met_tool}|{n_previous}".encode()))
    return measure(lot["_true_sites"], met_tool, t, case.hidden["world"], rng)


# -------------------------------------------------------------- benchmark set

DEV_SEEDS = [1, 2, 3, 4]
HOLDOUT_SEEDS = [5, 6]  # first held-out set, run once on Oct 28
HOLDOUT2_SEEDS = [7, 8]  # fresh held-out set for the version fixed after reading holdout failures


def benchmark(split: str = "dev") -> list:
    seeds = {
        "dev": DEV_SEEDS,
        "holdout": HOLDOUT_SEEDS,
        "holdout2": HOLDOUT2_SEEDS,
        "all": DEV_SEEDS + HOLDOUT_SEEDS + HOLDOUT2_SEEDS,
    }[split]
    return [f"{s}-{seed}" for s in SCENARIOS for seed in seeds]


def load(case_id: str) -> Case:
    scenario, seed = case_id.rsplit("-", 1)
    return generate(scenario, int(seed))
