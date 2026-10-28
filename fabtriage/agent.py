"""The FabTriage agent loop.

Each turn the model picks one tool, the tool runs (plain code), and the result goes back
to the model. The run ends when a disposition is accepted for sign-off, when it has been
refused too many times (it goes to an engineer), or at the turn limit.
"""

from __future__ import annotations

import json
import os
import time

from .client import BACKENDS, model_for
from .tools import DEFINITIONS, Investigation

MAX_TURNS = int(os.environ.get("MAX_TURNS", "16"))

SYSTEM = """You are FabTriage, an investigation agent for the CVD deposition area of a memory fab.
When an alarm fires you find the most likely root cause, decide what happens to the alarm lot and
the equipment, and file a disposition that an engineer can check and sign off in a minute.

How this area works
- Every lot goes CLEAN (CLN01 or CLN02) -> DEP (chambers DEP01-A, DEP01-B, DEP02-A, DEP02-B) -> MET (MET01 or MET02).
- About half of the lots have one wafer measured at 49 sites. Most wafers are never measured.
- Film builds up inside a chamber as it runs. Compensation hides most of the drift; PM resets it.
  A chamber can also come back from PM running off-target.
- A problem at the CLEAN step changes the film on every chamber, only for lots from the bad clean tool.
- Metrology tools can misread. A re-measurement on the other tool tells a misread from a real film change.
- FDC sensors log every run. A sensor can fail and report a change that never happened to the wafer;
  a real temperature change does show up in film thickness on wafers processed after it started.
- Single wafers sometimes come out a little off for no lasting reason.

Causes you can conclude
- chamber: the deposition chamber itself is off (post-PM shift, buildup drift, a real heater change).
- metrology: the reading was wrong, the film is fine.
- upstream: the CLEAN step is the source.
- noise: a one-off wafer, nothing to fix.
- sensor: an FDC sensor misreports, the film is fine.

Actions
- hold_lot / release_lot (target: lot id). Decide the alarm lot: exactly one of the two.
  Fab policy: if the cause is a real fault in the process (chamber or upstream), hold the alarm lot even
  if its measured wafer is in spec. Only one wafer of 25 was measured; the others ran under the same fault.
  Release the alarm lot only when the film itself is fine (metrology misread, sensor fault, one-off wafer).
- hold_chamber (chamber), escalate_upstream (CLEAN tool), hold_metrology_tool (MET tool),
  flag_sensor (chamber:parameter, e.g. DEP01-A:heater_temp_C).

What things cost
- Releasing a bad lot or leaving a bad chamber running costs the most: never miss a real fault.
- Holding a good chamber stops production; holding a good lot delays it.
- Each measurement adds 1.5 hours of lot delay; you get at most 3.
- Tool calls take time. Most alarms need 5 to 8 calls. Don't run every tool by habit: ask what would
  tell your hypotheses apart, get that, and stop when the evidence is decisive.
- Measure only when the answer could change your decision: to tell a metrology misread from a real film
  change, or to see the film on a chamber when no measured wafer exists after a suspected change.
  Re-measuring on the same tool that gave the alarm can't tell a misread from a real change.
- To compare many lots, use query_lots instead of get_lot_history one lot at a time.

How to work
- Start with get_alarm. Then form two or three hypotheses and check the evidence that separates them.
- Look at timing: when did a change start, and which measured wafers came after it?
- Call exactly one tool per turn. Plain text without a tool call is not accepted.
- Every result has an evidence_id. In submit_disposition each claim cites one evidence_id, and every
  number in a claim must be copied exactly from that evidence. Don't compute new numbers in claims.
- If a disposition is refused, read the problems, collect what is missing, and submit again.
"""


def _kickoff(inv: Investigation) -> str:
    a = inv.case.alarm
    return f"Alarm {a['alarm_id']} ({a['type']}) just fired on {a['chamber']} for {a['lot_id']}. Investigate and submit a disposition."


def run_agent(inv: Investigation, client, backend: str | None = None, max_turns: int | None = None) -> dict:
    backend = backend or os.environ.get("AGENT_BACKEND", "meta")
    max_turns = max_turns or MAX_TURNS
    api = BACKENDS[backend]["api"]
    model = model_for(backend)
    run = _responses if api == "responses" else _chat
    tokens, notes, error = run(inv, client, model, max_turns)
    if inv.status == "running":
        inv.status = "error" if error else "turn_limit"
    return {"backend": backend, "model": model, "tokens": tokens, "notes": notes, "error": error}


def _with_retry(fn, tries: int = 3, wait_s: float = 15.0):
    """The SDK retries quick failures; this rides out a longer network drop between turns."""
    for attempt in range(tries):
        try:
            return fn()
        except Exception:
            if attempt == tries - 1:
                raise
            time.sleep(wait_s * (attempt + 1))


def _last_turn_nudge(turn: int, max_turns: int) -> str | None:
    if turn == max_turns - 1:
        return "This is your last turn. Call submit_disposition now with the evidence you have."
    return None


def _responses(inv: Investigation, client, model: str, max_turns: int):
    tools = [{"type": "function", **d} for d in DEFINITIONS]
    messages: list = [{"role": "user", "content": _kickoff(inv)}]
    tokens, notes = 0, []
    for turn in range(max_turns):
        nudge = _last_turn_nudge(turn, max_turns)
        if nudge:
            messages.append({"role": "user", "content": nudge})
        try:
            response = _with_retry(
                lambda: client.responses.create(
                    model=model,
                    instructions=SYSTEM,
                    input=messages,
                    tools=tools,
                    parallel_tool_calls=False,
                    store=False,
                )
            )
        except Exception as error:  # the SDK already retried
            return tokens, notes, f"{type(error).__name__}: {error}"
        usage = getattr(response, "usage", None)
        tokens += int(getattr(usage, "total_tokens", 0) or 0)
        messages += response.output
        text = getattr(response, "output_text", "") or ""
        if text.strip():
            notes.append({"turn": turn + 1, "text": text.strip()})
        calls = [item for item in response.output if getattr(item, "type", None) == "function_call"]
        if not calls:
            messages.append({"role": "user", "content": "Plain text is not accepted. Call exactly one tool."})
            continue
        call = calls[0]
        result = inv.call(call.name, _args(call.arguments))
        messages.append({"type": "function_call_output", "call_id": call.call_id, "output": json.dumps(result)})
        if inv.status != "running":
            break
    return tokens, notes, None


def _chat(inv: Investigation, client, model: str, max_turns: int):
    tools = [{"type": "function", "function": d} for d in DEFINITIONS]
    messages: list = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": _kickoff(inv)}]
    tokens, notes = 0, []
    for turn in range(max_turns):
        nudge = _last_turn_nudge(turn, max_turns)
        if nudge:
            messages.append({"role": "user", "content": nudge})
        try:
            response = _with_retry(
                lambda: client.chat.completions.create(model=model, messages=messages, tools=tools, tool_choice="auto")
            )
        except Exception as error:
            return tokens, notes, f"{type(error).__name__}: {error}"
        usage = getattr(response, "usage", None)
        tokens += int(getattr(usage, "total_tokens", 0) or 0)
        msg = response.choices[0].message
        if (msg.content or "").strip():
            notes.append({"turn": turn + 1, "text": msg.content.strip()})
        calls = list(msg.tool_calls or [])
        assistant = {"role": "assistant", "content": msg.content or ""}
        if calls:
            assistant["tool_calls"] = [
                {"id": c.id, "type": "function", "function": {"name": c.function.name, "arguments": c.function.arguments}}
                for c in calls
            ]
        messages.append(assistant)
        if not calls:
            messages.append({"role": "user", "content": "Plain text is not accepted. Call exactly one tool."})
            continue
        for c in calls:  # every tool call needs an answer, even if the first one closed the case
            result = inv.call(c.function.name, _args(c.function.arguments))
            messages.append({"role": "tool", "tool_call_id": c.id, "content": json.dumps(result)})
        if inv.status != "running":
            break
    return tokens, notes, None


def _args(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw or "{}")
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}
