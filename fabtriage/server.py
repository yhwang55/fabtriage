"""The FabTriage console: a local web app for watching, reviewing and signing off investigations.

    python -m fabtriage serve            # http://127.0.0.1:8770

Reads and writes runs/<method>/<case>/run.json. Live agent runs need MODEL_API_KEY in .env.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import evaluate, sim, wafermap
from .client import has_key, make_client

WEB = Path(__file__).parent / "web"
RUNS = Path("runs")
METHODS = ["agent", "playbook", "always_hold", "agent_noverify", "oneshot", "agent_baseten", "agent_llama"]
EXPORT = Path("docs/demo")  # the static export; a hosted console with no runs/ seeds itself from it
_live: dict = {}  # case_id -> thread
_lock = threading.Lock()

# Public demo guard: live runs cost API credit, so a hosted console allows a fixed number a day.
LIVE_DAILY_CAP = int(os.environ.get("LIVE_DAILY_CAP", "0") or 0)  # 0 means no cap (local use)
LIVE_MAX_CONCURRENT = 3
_live_log = RUNS / "live_starts.json"


def seed_from_export() -> int:
    """If runs/ has no saved investigations but the static export exists, copy its runs back in.

    A hosted copy of the console starts from a fresh clone, where runs/ is not in git but
    docs/demo is. Returns the number of runs copied."""
    if (RUNS / "agent").exists() or not (EXPORT / "data" / "run").exists():
        return 0
    n = 0
    for f in (EXPORT / "data" / "run").glob("*/*.json"):
        run = json.loads(f.read_text()).get("run")
        if run:
            dest = RUNS / f.parent.name / f.stem / "run.json"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(json.dumps(run, default=str))
            n += 1
    for f in (EXPORT / "maps").glob("*/*/*.png"):
        dest = RUNS / f.parent.parent.name / f.parent.name / "maps" / f.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(f, dest)
    for f in (EXPORT / "data" / "recovery" / "run").glob("*/*.json"):
        run = json.loads(f.read_text()).get("run")
        if run:
            dest = RUNS / "recovery" / f.parent.name / f.stem / "run.json"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(json.dumps(run, default=str))
            n += 1
    return n


def live_budget() -> dict:
    """How many live runs started today (UTC) and how many are allowed."""
    today = time.strftime("%Y-%m-%d", time.gmtime())
    used = 0
    if _live_log.exists():
        try:
            log = json.loads(_live_log.read_text())
            used = log.get(today, 0)
        except ValueError:
            pass
    return {"cap": LIVE_DAILY_CAP, "used": used, "left": (LIVE_DAILY_CAP - used) if LIVE_DAILY_CAP else None, "running": len(_live)}


def _count_live_start() -> None:
    today = time.strftime("%Y-%m-%d", time.gmtime())
    log = {}
    if _live_log.exists():
        try:
            log = json.loads(_live_log.read_text())
        except ValueError:
            log = {}
    log = {today: log.get(today, 0) + 1}  # only today matters
    _live_log.parent.mkdir(parents=True, exist_ok=True)
    _live_log.write_text(json.dumps(log))


def _run_path(method: str, case_id: str) -> Path:
    if method not in METHODS or case_id not in sim.benchmark("all"):
        raise ValueError("unknown method or case")
    return RUNS / method / case_id / "run.json"


def _read_run(method: str, case_id: str) -> dict | None:
    path = _run_path(method, case_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except ValueError:  # mid-write during a live run; the next poll gets it
        return None


def cases() -> list:
    out = []
    for split in ("dev", "holdout", "holdout2", "holdout3"):
        for cid in sim.benchmark(split):
            case = sim.load(cid)
            runs = {}
            for m in METHODS:
                run = _read_run(m, cid)
                if run:
                    d = run.get("disposition") or {}
                    runs[m] = {
                        "status": run.get("status"),
                        "correct": (run.get("score") or {}).get("decision_correct"),
                        "signoff": (run.get("signoff") or {}).get("decision"),
                        "live": bool(run.get("live")) or cid in _live,
                        "cause": d.get("cause"),
                        "actions": [a.get("type") for a in d.get("actions") or [] if isinstance(a, dict)],
                        "measurements": (run.get("costs") or {}).get("measurements"),
                    }
            out.append({"case_id": cid, "split": split, "alarm": case.alarm, "runs": runs})
    return out


def context(case_id: str) -> dict:
    """Display-only history for the chart: what an engineer's SPC screen would show."""
    case = sim.load(case_id)
    c = case.alarm["chamber"]
    start = case.now_h - 24
    points = [
        {
            "t": lot["time_h"],
            "v": lot["measurement"]["mean"],
            "lot": lot["lot_id"],
            "chamber": lot["chamber"],
            "met": lot["measurement"]["met_tool"],
        }
        for lot in case.lots
        if lot["time_h"] > start and lot["measurement"] is not None
    ]
    fdc = [
        {"t": lot["time_h"], "v": lot["fdc"]["heater_temp_C"]}
        for lot in case.lots
        if lot["time_h"] > start and lot["chamber"] == c
    ]
    return {
        "alarm": case.alarm,
        "chamber": c,
        "points": points,
        "heater": fdc,
        "pm": [p["time_h"] for p in case.pm_log if p["chamber"] == c and p["time_h"] > start],
        "limits": {"lsl": sim.LSL, "usl": sim.USL, "lcl": sim.LCL, "ucl": sim.UCL, "target": sim.TARGET},
        "window": [start, case.now_h],
    }


def wafer_png(case_id: str, lot_id: str) -> bytes | None:
    case = sim.load(case_id)
    lot = case.lot(lot_id)
    if lot["measurement"] is None:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        path = wafermap.render(lot["measurement"]["sites"], Path(tmp) / "m.png")
        return path.read_bytes()


def benchmark() -> dict:
    if not (RUNS / "results_agent_holdout3.json").exists() and (EXPORT / "data" / "benchmark.json").exists():
        return json.loads((EXPORT / "data" / "benchmark.json").read_text())  # hosted copy: results live in the export
    out = {}
    for split in ("dev", "holdout", "holdout2", "holdout3"):
        out[split] = {}
        for m in METHODS:
            path = RUNS / f"results_{m}_{split}.json"
            if path.exists():
                data = json.loads(path.read_text())
                out[split][m] = {"summary": data["summary"], "rows": data["rows"]}
            rep = RUNS / f"results_{m}_{split}_repeats.json"
            if rep.exists() and m in out[split]:
                r = json.loads(rep.read_text())
                out[split][m]["repeats"] = {k: r[k] for k in ("repeats", "mean_std", "cases_always_right", "cases_sometimes_wrong")}
        from .impact import table

        out[split + "_impact"] = table(RUNS, split)
    out["recovery"] = recovery_benchmark()
    sw = RUNS / "sweep.json"
    out["sweep"] = json.loads(sw.read_text()) if sw.exists() else None
    sw2 = RUNS / "sweep_stress2.json"
    out["sweep2"] = json.loads(sw2.read_text()) if sw2.exists() else None
    out["report"] = {}
    for split in ("holdout3",):
        path = RUNS / f"report_{split}.json"
        if path.exists():
            out["report"][split] = json.loads(path.read_text())
    return out


# ---------------------------------------------------------------- recovery after PM
REC_METHODS = ["agent", "agent_baseten", "agent_llama", "monitor_rule", "reset_recipe", "keep_recipe"]


def recovery_cases() -> list:
    from . import recovery as R

    out = []
    for split in ("linked", "dev", "holdout", "holdout2", "holdout3"):
        for cid in R.benchmark(split):
            c = R.load(cid)
            runs = {}
            for m in REC_METHODS:
                path = RUNS / "recovery" / m / cid / "run.json"
                if path.exists():
                    try:
                        sc = json.loads(path.read_text()).get("score") or {}
                    except ValueError:
                        continue
                    runs[m] = {k: sc.get(k) for k in ("status", "off_target_lots", "out_of_spec_lots", "monitor_wafers", "recipe_change_pct")}
            out.append({"case_id": cid, "split": split, "chamber": c.chamber, "pm": c.pm, "pre_pm_time_s": c.pre_pm_time_s, "origin": c.origin, "runs": runs})
    return out


def recovery_run(method: str, case_id: str) -> dict | None:
    from . import recovery as R

    if method not in REC_METHODS or case_id not in R.all_ids():
        raise ValueError("unknown method or case")
    path = RUNS / "recovery" / method / case_id / "run.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except ValueError:
        return None


def recovery_benchmark() -> dict:
    from . import recovery_eval as RE

    out = {}
    for split in ("dev", "holdout", "holdout2", "holdout3"):
        res = RE.load_results(RUNS / "recovery", split)
        out[split] = {m: {"summary": d["summary"], "repeats": (d.get("repeats") or {}).get("mean_std")} for m, d in res.items()}
        out[split + "_criteria"] = RE.criteria(res)
    return out


def start_live(case_id: str, engineer_note: str | None = None) -> dict:
    if not has_key("meta"):
        return {"error": "MODEL_API_KEY is not set in .env, so live runs are off. Recorded runs still work."}
    if case_id in sim.benchmark("holdout") + sim.benchmark("holdout2") + sim.benchmark("holdout3"):
        return {"error": "This alarm is held out for the final benchmark. Use a development alarm for live runs."}
    with _lock:
        if case_id in _live:
            return {"error": "an investigation is already running for this alarm"}
        if len(_live) >= LIVE_MAX_CONCURRENT:
            return {"error": f"{LIVE_MAX_CONCURRENT} investigations are already running; try again in a minute"}
        if LIVE_DAILY_CAP:
            b = live_budget()
            if b["left"] <= 0:
                return {"error": f"Today's {LIVE_DAILY_CAP} live investigations are used up (the public demo has a daily budget). Recorded runs still work; the budget resets at 00:00 UTC."}
            _count_live_start()
        previous = _read_run("agent", case_id)
        history = list((previous or {}).get("history") or [])
        if previous and previous.get("disposition"):
            history.append(
                {
                    "disposition": previous.get("disposition"),
                    "signoff": previous.get("signoff"),
                    "costs": previous.get("costs"),
                }
            )
        client = make_client("meta")

        def work():
            try:
                row = evaluate.run_one(
                    "agent",
                    case_id,
                    RUNS,
                    client,
                    "meta",
                    sam_client=client,
                    engineer_note=engineer_note,
                    autosave=True,
                    keep={"history": history, "engineer_note": engineer_note},
                )
                print(f"live run {case_id}: {row['status']}", flush=True)
            finally:
                with _lock:
                    _live.pop(case_id, None)

        thread = threading.Thread(target=work, daemon=True)
        _live[case_id] = thread
        thread.start()
    return {"started": True}


def signoff(method: str, case_id: str, decision: str, note: str) -> dict:
    if decision not in ("approve", "reject"):
        return {"error": "decision must be approve or reject"}
    run = _read_run(method, case_id)
    if not run or run.get("status") != "awaiting_signoff":
        return {"error": "this investigation is not waiting for sign-off"}
    run["signoff"] = {"decision": decision, "note": note, "at": time.strftime("%Y-%m-%d %H:%M")}
    _run_path(method, case_id).write_text(json.dumps(run, indent=2, default=str))
    out = {"saved": True}
    if decision == "reject" and method == "agent" and note.strip():
        out["rerun"] = start_live(case_id, note.strip())
    return out


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, body: bytes, kind: str = "application/json", code: int = 200):
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, code: int = 200):
        self._send(json.dumps(data, default=str).encode(), code=code)

    def do_GET(self):
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            if url.path in ("/", "/index.html"):
                return self._send((WEB / "index.html").read_bytes(), "text/html; charset=utf-8")
            if url.path == "/api/cases":
                return self._json({"cases": cases(), "live_enabled": has_key("meta"), "live_budget": live_budget() if LIVE_DAILY_CAP else None})
            if url.path == "/api/run":
                from .sources import SOURCES

                scenario = q["case"].rsplit("-", 1)[0]
                return self._json(
                    {"run": _read_run(q["method"], q["case"]), "live": q["case"] in _live, "sources": SOURCES.get(scenario)}
                )
            if url.path == "/api/recovery/cases":
                return self._json({"cases": recovery_cases()})
            if url.path == "/api/recovery/run":
                return self._json({"run": recovery_run(q["method"], q["case"])})
            if url.path == "/api/context":
                return self._json(context(q["case"]))
            if url.path == "/api/benchmark":
                return self._json(benchmark())
            if url.path == "/api/wafer.png":
                png = wafer_png(q["case"], q["lot"])
                return self._send(png, "image/png") if png else self._json({"error": "not measured"}, 404)
            if url.path.startswith("/runs/"):
                parts = url.path.split("/")  # /runs/<method>/<case>/maps/<file>.png
                if len(parts) == 6 and parts[4] == "maps" and parts[5].endswith(".png"):
                    _run_path(parts[2], parts[3])
                    path = RUNS / parts[2] / parts[3] / "maps" / Path(parts[5]).name
                    if path.exists():
                        return self._send(path.read_bytes(), "image/png")
            self._json({"error": "not found"}, 404)
        except (KeyError, ValueError) as error:
            self._json({"error": str(error)}, 400)

    def do_POST(self):
        url = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        if length > 1024 * 1024:
            return self._json({"error": "request too large"}, 413)
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw or b"{}")
            if url.path == "/api/live":
                sim.load(body["case"])
                return self._json(start_live(body["case"], body.get("engineer_note")))
            if url.path == "/api/signoff":
                return self._json(signoff(body["method"], body["case"], body["decision"], body.get("note", "")))
            self._json({"error": "not found"}, 404)
        except (KeyError, ValueError) as error:
            self._json({"error": str(error)}, 400)


def serve(port: int = 8770, host: str = "127.0.0.1") -> None:
    n = seed_from_export()
    if n:
        print(f"seeded {n} saved runs from {EXPORT}", flush=True)
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"FabTriage console: http://{host}:{port}  (Ctrl+C to stop)" + (f"; live runs capped at {LIVE_DAILY_CAP} a day" if LIVE_DAILY_CAP else ""), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
