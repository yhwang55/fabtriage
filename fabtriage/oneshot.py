"""Ablation: the same model with no agency. Code collects a fixed evidence pack (the same
checks the playbook runs, minus measurements), the model reads it once and returns a
disposition. No follow-up questions, no extra measurements, no verifier enforcement.
"""

from __future__ import annotations

import json
import re

from .agent import SYSTEM, _with_retry
from .client import BACKENDS, model_for
from .tools import CAUSES, Investigation

INSTRUCTIONS = (
    SYSTEM.split("How to work")[0]
    + """How to answer
You get a fixed set of evidence below and cannot ask for more. Reply with one JSON object only:
{"cause": one of %s,
 "actions": [{"type": ..., "target": ...}],
 "claims": [{"evidence_id": "E1", "statement": "..."}],
 "summary": "two or three sentences"}
Every claim cites one evidence_id, and every number in it is copied from that evidence.
"""
    % CAUSES
)


def _evidence_pack(inv: Investigation) -> list:
    a = inv.call("get_alarm", {})
    alarm = a["alarm"]
    c, lot = alarm["chamber"], alarm["lot_id"]
    calls = [
        ("get_lot_history", {"lot_id": lot}),
        ("get_chamber_summary", {"window_hours": 24}),
        ("get_trend", {"chamber": c, "signal": "thickness", "window_hours": 24}),
        ("get_trend", {"chamber": c, "signal": "heater_temp_C", "window_hours": 24}),
        ("run_commonality", {"window_hours": 12}),
        ("get_fdc_summary", {"chamber": c, "recent_hours": 4}),
        ("get_pm_log", {"chamber": c}),
        ("query_lots", {"window_hours": 12}),
    ]
    pack = [a]
    for name, args in calls:
        pack.append({"tool": name, "args": args, **inv.call(name, args)})
    return pack


def _parse(text: str) -> dict | None:
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        return None
    try:
        value = json.loads(match.group(0))
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def run_oneshot(inv: Investigation, client, backend: str | None = None) -> dict:
    backend = backend or "meta"
    model = model_for(backend)
    inv.verify_enabled = False  # one shot: no chance to fix a refusal, so record problems instead
    pack = _evidence_pack(inv)
    user = "Evidence collected for this alarm:\n\n" + json.dumps(pack, indent=1)
    try:
        if BACKENDS[backend]["api"] == "responses":
            response = _with_retry(
                lambda: client.responses.create(model=model, instructions=INSTRUCTIONS, input=user, store=False)
            )
            text = response.output_text
        else:
            response = _with_retry(
                lambda: client.chat.completions.create(
                    model=model, messages=[{"role": "system", "content": INSTRUCTIONS}, {"role": "user", "content": user}]
                )
            )
            text = response.choices[0].message.content
    except Exception as error:  # the SDK and _with_retry already retried
        inv.status = "error"
        return {"backend": backend, "model": model, "tokens": 0, "error": f"{type(error).__name__}: {error}"}
    usage = getattr(response, "usage", None)
    tokens = int(getattr(usage, "total_tokens", 0) or 0)
    d = _parse(text)
    if d is None:
        inv.status = "error"
        return {"backend": backend, "model": model, "tokens": tokens, "error": "no JSON in reply", "raw": text}
    inv.call(
        "submit_disposition",
        {
            "cause": d.get("cause"),
            "actions": d.get("actions") or [],
            "claims": d.get("claims") or [],
            "summary": d.get("summary") or "",
        },
    )
    return {"backend": backend, "model": model, "tokens": tokens}
