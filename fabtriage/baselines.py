"""Two baselines that go through the same tools and the same verification as the agent.

always_hold: what happens by default on the floor: any alarm holds the lot and the chamber.
playbook:    a fixed, rule-based playbook: run every check in a fixed order, then decide
             with fixed thresholds. No judgment about which evidence matters.
"""

from __future__ import annotations

from . import sim
from .tools import Investigation

PLAYBOOK_CHAMBER_DELTA = 5.0  # A above the other chambers' mean
PLAYBOOK_P = 0.01


def always_hold(inv: Investigation) -> None:
    a = inv.call("get_alarm", {})
    s = inv.call("get_chamber_summary", {"window_hours": 24})
    alarm = a["alarm"]
    c = alarm["chamber"]
    trend = inv.call("get_trend", {"chamber": c, "signal": "thickness", "window_hours": 24})
    claims = [
        {"evidence_id": a["evidence_id"], "statement": f"Alarm {alarm['type']} on {c} with value {alarm['value']}."},
        {"evidence_id": s["evidence_id"], "statement": f"{c} has {s['chambers'][c]['n_measured']} measured wafers in 24 hours."},
    ]
    if trend.get("n_points"):
        claims.append({"evidence_id": trend["evidence_id"], "statement": f"Last measured value on {c} is {trend['last_value']}."})
    inv.call(
        "submit_disposition",
        {
            "cause": "chamber",
            "actions": [{"type": "hold_lot", "target": alarm["lot_id"]}, {"type": "hold_chamber", "target": c}],
            "claims": claims,
            "summary": "Default response: hold the lot and the chamber until an engineer reviews.",
        },
    )


def playbook(inv: Investigation) -> None:
    a = inv.call("get_alarm", {})
    alarm = a["alarm"]
    c, lot = alarm["chamber"], alarm["lot_id"]
    summary = inv.call("get_chamber_summary", {"window_hours": 24})
    common = inv.call("run_commonality", {"window_hours": 12})
    trend = inv.call("get_trend", {"chamber": c, "signal": "thickness", "window_hours": 24})
    fdc = inv.call("get_fdc_summary", {"chamber": c, "recent_hours": 4})
    remeasure = None
    if alarm["type"] in ("OOS", "OOC"):
        other = "MET01" if alarm["met_tool"] == "MET02" else "MET02"
        remeasure = inv.call("request_measurement", {"lot_id": lot, "met_tool": other})
        inv.call("get_wafer_map", {"lot_id": lot})

    rows = summary["chambers"]
    others = [rows[o]["mean_A"] for o in sim.CHAMBERS if o != c and "mean_A" in rows[o]]
    delta = rows[c].get("mean_A", sim.TARGET) - (sum(others) / len(others) if others else sim.TARGET)
    clean = common["steps"]["CLEAN"]
    alarm_claim = {"evidence_id": a["evidence_id"], "statement": f"{alarm['type']} alarm on {c}, value {alarm['value']}."}

    def submit(cause, actions, claims, text):
        inv.call("submit_disposition", {"cause": cause, "actions": actions, "claims": [alarm_claim] + claims, "summary": text})

    if alarm["type"] == "FDC":
        recent = fdc["recent_measured_wafers"]
        ok = trend.get("n_points") and sim.LCL <= trend["last_value"] <= sim.UCL
        if ok:
            submit(
                "sensor",
                [{"type": "flag_sensor", "target": f"{c}:{alarm['parameter']}"}, {"type": "release_lot", "target": lot}],
                [{"evidence_id": trend["evidence_id"], "statement": f"Last thickness on {c} is {trend['last_value']}, in control."}]
                + ([{"evidence_id": fdc["evidence_id"], "statement": f"{len(recent)} recent wafers measured on {c}."}] if recent else []),
                "FDC alarm but film thickness is in control: treat as a sensor fault.",
            )
        else:
            submit(
                "chamber",
                [{"type": "hold_lot", "target": lot}, {"type": "hold_chamber", "target": c}],
                [
                    {"evidence_id": summary["evidence_id"], "statement": f"{c} 24 hour mean is {rows[c].get('mean_A')}."},
                    {"evidence_id": trend["evidence_id"], "statement": f"Trend checked on {c}."},
                ],
                "FDC alarm and thickness not clearly in control: hold.",
            )
        return

    if remeasure and remeasure.get("in_spec") and alarm["type"] == "OOS":
        submit(
            "metrology",
            [{"type": "release_lot", "target": lot}],
            [{"evidence_id": remeasure["evidence_id"], "statement": f"Re-measured on {remeasure['met_tool']}: {remeasure['mean_A']}, in spec."}],
            "Re-measurement is in spec: the first reading was a metrology problem.",
        )
    elif clean["anova_p_value"] is not None and clean["anova_p_value"] < PLAYBOOK_P:
        tool = clean["most_deviant_tool"]
        submit(
            "upstream",
            [{"type": "hold_lot", "target": lot}, {"type": "escalate_upstream", "target": tool}],
            [{"evidence_id": common["evidence_id"], "statement": f"CLEAN step p-value {clean['anova_p_value']}, most deviant tool {tool}."}],
            "Lots differ by clean tool: escalate upstream.",
        )
    elif delta > PLAYBOOK_CHAMBER_DELTA:
        submit(
            "chamber",
            [{"type": "hold_lot", "target": lot}, {"type": "hold_chamber", "target": c}],
            [
                {"evidence_id": summary["evidence_id"], "statement": f"{c} 24 hour mean is {rows[c]['mean_A']}."},
                {"evidence_id": trend["evidence_id"], "statement": f"Last value on {c} is {trend['last_value']}."},
            ],
            "Alarm chamber runs well above the others: hold it.",
        )
    elif alarm["type"] == "OOC":
        submit(
            "noise",
            [{"type": "release_lot", "target": lot}],
            [{"evidence_id": summary["evidence_id"], "statement": f"{c} 24 hour mean is {rows[c].get('mean_A')}."}],
            "Single out-of-control point with a normal chamber: release.",
        )
    else:
        submit(
            "chamber",
            [{"type": "hold_lot", "target": lot}, {"type": "hold_chamber", "target": c}],
            [
                {"evidence_id": summary["evidence_id"], "statement": f"{c} 24 hour mean is {rows[c].get('mean_A')}."},
                {"evidence_id": trend["evidence_id"], "statement": f"Trend checked on {c}."},
            ],
            "Out of spec with no other explanation: hold to be safe.",
        )


BASELINES = {"always_hold": always_hold, "playbook": playbook}
