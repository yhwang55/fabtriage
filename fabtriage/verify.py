"""The verification layer: plain-code checks that run inside submit_disposition, so the
agent can't skip them. They never look at the hidden truth. They check that the
disposition is grounded in evidence the agent actually collected and that it follows
the fab's playbook (for example: never release an out-of-spec lot without an in-spec
re-measurement).

check(inv, disposition) -> list of problems; empty means accepted.
"""

from __future__ import annotations

import json
import re

from . import sim

_ID = re.compile(r"\b(?:[A-Z]{1,4}\d*-)+[A-Z0-9]+\b|\b[A-Z]{2,4}\d+\b|\bE\d+\b|\b\w+_\w+\b")
_NUM = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?")
FREE_NUMBERS = {sim.LSL, sim.USL, sim.LCL, sim.UCL, sim.TARGET}


_UNITS = re.compile(r"\bper\s+100\s+wafers?\b", re.I)  # "A per 100 wafers" is a unit, not a claim


def numbers_in(text: str) -> list:
    return [m.group(0) for m in _NUM.finditer(_ID.sub(" ", _UNITS.sub(" ", text)))]


def _flatten(obj, out):
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        out.append(float(obj))
    elif isinstance(obj, str):
        out.extend(float(n) for n in numbers_in(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            _flatten(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _flatten(v, out)


def evidence_numbers(result: dict) -> list:
    out: list = []
    _flatten(result, out)
    return out


def grounded(token: str, pool: list) -> bool:
    value = float(token)
    if value in FREE_NUMBERS or (value.is_integer() and 0 <= value <= 10):
        return True
    decimals = len(token.split(".")[1]) if "." in token else 0
    for e in pool:
        if abs(e - value) < 0.011 or round(e, decimals) == value:
            return True
    return False


def _valid_target(kind: str, target: str, case: sim.Case) -> str | None:
    lots = {lot["lot_id"] for lot in case.lots}
    if kind in ("hold_lot", "release_lot"):
        return None if target in lots else f"{kind}: unknown lot {target!r}"
    if kind == "hold_chamber":
        return None if target in sim.CHAMBERS else f"hold_chamber: unknown chamber {target!r}"
    if kind == "escalate_upstream":
        return None if target in sim.CLEAN_TOOLS else f"escalate_upstream: {target!r} is not an upstream (CLEAN) tool"
    if kind == "hold_metrology_tool":
        return None if target in sim.MET_TOOLS else f"hold_metrology_tool: unknown tool {target!r}"
    if kind == "flag_sensor":
        chamber, _, param = target.partition(":")
        if chamber in sim.CHAMBERS and param in sim.FDC_PARAMS:
            return None
        return f"flag_sensor: target must be chamber:parameter, got {target!r}"
    return f"unknown action type {kind!r}"


def check(inv, d: dict) -> list:
    case, alarm = inv.case, inv.case.alarm
    problems: list = []
    cause = d.get("cause")
    actions = [(str(a.get("type")), str(a.get("target"))) for a in d.get("actions") or [] if isinstance(a, dict)]
    claims = [c for c in d.get("claims") or [] if isinstance(c, dict)]

    if cause not in ("chamber", "metrology", "upstream", "noise", "sensor"):
        problems.append(f"rule: unknown cause {cause!r}")
    for kind, target in actions:
        err = _valid_target(kind, target, case)
        if err:
            problems.append("rule: " + err)

    # ---- grounding: every claim cites real evidence, every number is in it
    cited = set()
    if len(claims) < 2:
        problems.append("rule: give at least two claims, each citing the evidence it rests on")
    for i, c in enumerate(claims, 1):
        eid, text = str(c.get("evidence_id", "")), str(c.get("statement", ""))
        if eid not in inv.evidence:
            problems.append(f"claim {i}: evidence {eid!r} does not exist")
            continue
        cited.add(eid)
        pool = evidence_numbers(inv.evidence[eid]["result"])
        missing = [n for n in numbers_in(text) if not grounded(n, pool)]
        if missing:
            problems.append(
                f"claim {i}: number(s) {', '.join(missing)} do not appear in {eid}; copy numbers exactly from the evidence"
            )
    if len(cited) < 2 and len(claims) >= 2:
        problems.append("rule: cite at least two different pieces of evidence")
    cited_tools = {inv.evidence[e]["tool"] for e in cited}
    cited_args = [inv.evidence[e]["args"] for e in cited]

    # ---- the alarm lot gets exactly one decision
    alarm_lot = alarm["lot_id"]
    held = ("hold_lot", alarm_lot) in actions
    released = ("release_lot", alarm_lot) in actions
    if held == released:
        problems.append(f"rule: decide the alarm lot {alarm_lot}: exactly one of hold_lot or release_lot")
    in_spec_remeasure = any(m["lot_id"] == alarm_lot and m["in_spec"] for m in inv.measurements)
    if alarm["type"] == "OOS" and released and not in_spec_remeasure:
        problems.append("rule: an out-of-spec lot can't be released without an in-spec re-measurement of it")

    kinds = {k for k, _ in actions}
    # ---- cause-specific minimum evidence (the playbook)
    if cause == "chamber":
        if "hold_chamber" not in kinds:
            problems.append("rule: cause 'chamber' needs a hold_chamber action")
        if not cited_tools & {"get_chamber_summary", "run_commonality"}:
            problems.append("rule: cause 'chamber' needs cited evidence comparing chambers (get_chamber_summary or run_commonality)")
        for k, target in actions:
            if k == "hold_chamber" and not any(a.get("chamber") == target for a in cited_args):
                problems.append(f"rule: holding {target} needs cited evidence about {target} itself (get_trend or get_fdc_summary)")
    if cause == "metrology":
        if not in_spec_remeasure:
            problems.append("rule: cause 'metrology' needs an in-spec re-measurement of the alarm lot")
        if "request_measurement" not in cited_tools:
            problems.append("rule: cause 'metrology' must cite the re-measurement")
    if cause == "upstream":
        if "escalate_upstream" not in kinds:
            problems.append("rule: cause 'upstream' needs an escalate_upstream action")
        if "run_commonality" not in cited_tools:
            problems.append("rule: cause 'upstream' must cite run_commonality")
    if cause == "noise":
        if alarm["type"] == "OOS" and not in_spec_remeasure:
            problems.append("rule: an out-of-spec alarm can't be called noise without an in-spec re-measurement")
        if not cited_tools & {"get_trend", "get_chamber_summary"}:
            problems.append("rule: cause 'noise' must cite the chamber's history (get_trend or get_chamber_summary)")
    if cause == "sensor":
        if "flag_sensor" not in kinds:
            problems.append("rule: cause 'sensor' needs a flag_sensor action")
        thickness = any(
            (inv.evidence[e]["tool"] == "get_trend" and inv.evidence[e]["args"].get("signal") == "thickness")
            or inv.evidence[e]["tool"] in ("request_measurement", "get_fdc_summary")
            for e in cited
        )
        if not thickness:
            problems.append("rule: cause 'sensor' must cite film thickness on that chamber, to show the film is unaffected")
    if cause in ("metrology", "upstream", "noise", "sensor") and "hold_chamber" in kinds:
        problems.append(f"rule: cause {cause!r} contradicts holding a chamber; pick the cause the evidence supports")
    return problems


def dumps(d) -> str:
    return json.dumps(d, indent=2)
