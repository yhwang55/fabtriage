"""Command line.

    python -m fabtriage cases [--split dev]
    python -m fabtriage eval --method playbook --split dev
    python -m fabtriage eval --method agent --split dev --backend meta --limit 3
    python -m fabtriage run --case pm_shift-1 --method agent
    python -m fabtriage compare --split dev
    python -m fabtriage serve            # the console at http://127.0.0.1:8770
    python -m fabtriage recover --method agent --split dev     # recovery after PM
    python -m fabtriage recover-report --split holdout
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from . import evaluate, sim
from .client import has_key, load_env, make_client

RUNS = Path("runs")


def _clients(method: str, backend: str):
    if method not in ("agent", "agent_noverify", "oneshot"):
        return None, None
    client = make_client(backend)
    sam = make_client("meta") if has_key("meta") else None
    return client, sam


def main(argv=None) -> None:
    load_env()
    p = argparse.ArgumentParser(prog="fabtriage")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("cases")
    c.add_argument("--split", default="all", choices=["dev", "holdout", "holdout2", "holdout3", "all"])
    e = sub.add_parser("eval")
    e.add_argument("--method", required=True, choices=["agent", "agent_noverify", "oneshot", "playbook", "always_hold"])
    e.add_argument("--split", default="dev", choices=["dev", "holdout", "holdout2", "holdout3", "all", "stress_L0", "stress_L1", "stress_L2", "stress_L3"])
    e.add_argument("--backend", default="meta", choices=["meta", "baseten", "llama"])
    e.add_argument("--limit", type=int)
    e.add_argument("--only", nargs="*", help="scenario name prefixes, e.g. pm_shift heater_drift")
    e.add_argument("--repeats", type=int, default=1, help="run the split this many times and report mean and spread")
    e.add_argument("--resume", action="store_true", help="skip cases that already have a saved run (after an interruption)")
    r = sub.add_parser("run")
    r.add_argument("--case", required=True)
    r.add_argument("--method", default="agent", choices=["agent", "agent_noverify", "oneshot", "playbook", "always_hold"])
    r.add_argument("--backend", default="meta", choices=["meta", "baseten", "llama"])
    rs = sub.add_parser("rescore", help="rebuild a results file from saved runs")
    rs.add_argument("--method", required=True, choices=["agent", "agent_noverify", "oneshot", "playbook", "always_hold"])
    rs.add_argument("--split", default="dev", choices=["dev", "holdout", "holdout2", "holdout3", "all", "stress_L0", "stress_L1", "stress_L2", "stress_L3"])
    im = sub.add_parser("impact", help="per-100-alarm impact under stated assumptions")
    im.add_argument("--split", default="dev", choices=["dev", "holdout", "holdout2", "holdout3", "all"])
    rc = sub.add_parser("recover", help="recovery after PM: bring a held chamber back to target")
    rc.add_argument("--method", required=True, choices=["agent", "agent_v2", "monitor_rule", "reset_recipe", "keep_recipe", "oracle"])
    rc.add_argument("--split", default="dev", choices=["dev", "holdout", "holdout2", "holdout3", "all", "linked", "stress_L0", "stress_L1", "stress_L2", "stress_L3", "stress2_L0", "stress2_L1", "stress2_L2", "stress2_L3"])
    rc.add_argument("--backend", default="meta", choices=["meta", "baseten", "llama"])
    rc.add_argument("--only", nargs="*", help="scenario names, e.g. seasoning fast_drift")
    rc.add_argument("--repeats", type=int, default=1)
    rc.add_argument("--resume", action="store_true", help="skip recoveries that already have a saved run")
    rc.add_argument("--hide", nargs="*", default=[], choices=["history", "pm_detail"], help="ablation: hide clues from the agent")
    rr = sub.add_parser("recover-report", help="recovery results and the pre-registered success criteria")
    rr.add_argument("--split", default="holdout", choices=["dev", "holdout", "holdout2", "holdout3", "all"])
    sw = sub.add_parser("sweep-report", help="accuracy and off-target lots across stress levels")
    sw.add_argument("--prefix", default="stress", choices=["stress", "stress2"])
    fb = sub.add_parser("feedback", help="re-investigate the alarms the agent got wrong, with and without an engineer note")
    fb.add_argument("--split", default="stress_L3", choices=["dev", "holdout", "holdout2", "holdout3", "stress_L0", "stress_L1", "stress_L2", "stress_L3"])
    fb.add_argument("--backend", default="meta", choices=["meta", "baseten", "llama"])
    fb.add_argument("--resume", action="store_true")
    rp = sub.add_parser("report", help="confidence intervals for diagnosis and recovery on one split")
    rp.add_argument("--split", default="holdout3", choices=["dev", "holdout", "holdout2", "holdout3"])
    dm = sub.add_parser("demo", help="open the read-only demo from docs/demo; no API key needed")
    dm.add_argument("--port", type=int, default=8771)
    ex = sub.add_parser("export", help="write the console as a static read-only site")
    ex.add_argument("--out", default="docs/demo")
    ex.add_argument("--live-url", default=None, help="hosted console the static site links to for live runs")
    sv = sub.add_parser("serve")
    sv.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8770")))
    sv.add_argument("--host", default="127.0.0.1", help="0.0.0.0 to serve on all interfaces (hosted copy)")
    cmp_ = sub.add_parser("compare")
    cmp_.add_argument("--split", default="dev")
    args = p.parse_args(argv)

    if args.cmd == "cases":
        for cid in sim.benchmark(args.split):
            case = sim.load(cid)
            a = case.alarm
            print(f"{cid:20s} {a['type']:4s} {a['chamber']:8s} {a['value']!s:9s} confounder={case.truth['confounder']}")
    elif args.cmd == "eval" and args.repeats > 1:
        client, sam = _clients(args.method, args.backend)
        out = evaluate.run_repeats(args.method, args.split, RUNS, args.repeats, client, args.backend, sam, resume=args.resume)
        print(json.dumps({k: out[k] for k in ("mean_std", "cases_always_right", "cases_sometimes_wrong")}, indent=2))
    elif args.cmd == "eval":
        client, sam = _clients(args.method, args.backend)
        result = evaluate.run_split(
            args.method, args.split, RUNS, client, args.backend, args.limit, args.only, sam_client=sam, resume=args.resume
        )
        print(json.dumps(result["summary"], indent=2))
    elif args.cmd == "run":
        client, sam = _clients(args.method, args.backend)
        row = evaluate.run_one(args.method, args.case, RUNS, client, args.backend, sam)
        print(json.dumps(row, indent=2))
        print(f"trace: {RUNS / args.method / args.case / 'run.json'}")
    elif args.cmd == "rescore":
        print(json.dumps(evaluate.rescore(args.method, args.split, RUNS)["summary"], indent=2))
    elif args.cmd == "impact":
        from .impact import table

        t = table(RUNS, args.split)
        for k, v in t["assumptions"].items():
            print(f"assume {k} = {v['value']}  ({v['why']})")
        cols = ["engineer_hours", "needless_holds", "lot_hours_from_needless_holds", "lot_hours_from_measurements", "missed_faults", "lots_at_risk"]
        print("per 100 alarms".ljust(18) + "".join(c[:16].rjust(18) for c in cols))
        for method, row in t["methods"].items():
            print(method.ljust(18) + "".join(str(row[c]).rjust(18) for c in cols))
    elif args.cmd in ("recover", "recover-report"):
        from . import recovery_eval as RE

        rdir = RUNS / "recovery"
        if args.cmd == "recover":
            client = make_client(args.backend) if args.method in ("agent", "agent_v2") else None
            if args.repeats > 1:
                out = RE.run_repeats(args.method, args.split, rdir, args.repeats, client, args.backend, hide=args.hide, resume=args.resume)
                print(json.dumps(out["mean_std"], indent=2))
            else:
                out = RE.run_split(args.method, args.split, rdir, client, args.backend, args.only, hide=args.hide, resume=args.resume)
                print(json.dumps(out["summary"], indent=2))
        else:
            res = RE.load_results(rdir, args.split)
            cols = ["off_target_lots", "out_of_spec_lots", "avg_monitor_wafers", "avg_downtime_h", "needs_engineer", "rule_broken_cases", "no_shift_max_change_pct"]
            print("method".ljust(32) + "".join(c[:14].rjust(16) for c in cols))
            for m, d in res.items():
                print(m[:30].ljust(32) + "".join(str(d["summary"][c]).rjust(16) for c in cols))
            for c in RE.criteria(res):
                print(("MET  " if c["met"] else "MISS ") + f"{c['criterion']}: {c['value']}")
    elif args.cmd == "feedback":
        from . import feedback

        client, sam = _clients("agent", args.backend)
        out = feedback.run(args.split, RUNS, client, args.backend, sam, resume=args.resume)
        print(json.dumps({k: out[k] for k in ("n", "with_note", "no_note")}, indent=2))
    elif args.cmd == "sweep-report":
        from .stats import sweep

        data = sweep(RUNS, args.prefix)
        for kind, key, unit in (("diagnosis", "decision_accuracy_pct", "% right"), ("recovery", "off_target_per_recovery", " off-target lots per recovery")):
            print(kind)
            for m, levels in data[kind].items():
                cells = []
                for lv in levels:
                    if lv is None:
                        cells.append("   -   ")
                    else:
                        cells.append(f"{lv[key]} [{lv['ci'][0]}, {lv['ci'][1]}]")
                print(f"  {m:16s} " + "  |  ".join(cells))
    elif args.cmd == "report":
        from .stats import report

        data = report(RUNS, args.split)
        d, r = data["diagnosis"], data["recovery"]
        print(f"Diagnosis, {d['n_cases']} alarms (per-case mean over repeats, 95% bootstrap CI over cases)")
        for m, v in d["methods"].items():
            if v.get("incomplete"):
                print(f"  {m:24s} incomplete ({v['repeats']} repeat files)")
                continue
            print(f"  {m:24s} right decision {v['decision_accuracy_pct']}% [{v['ci95_pct'][0]}, {v['ci95_pct'][1]}]  "
                  f"missed faults {v['missed_faults_per_run']}  needless holds {v['needless_holds_per_run']}  repeats {v['repeats']}")
        for k, v in d["paired"].items():
            print(f"  {k:40s} {v['diff']} points [{v['ci95'][0]}, {v['ci95'][1]}]")
        print(f"Recovery, {r['n_cases']} recoveries")
        for m, v in r["methods"].items():
            if v.get("incomplete"):
                print(f"  {m:30s} incomplete ({v['repeats']} repeat files)")
                continue
            print(f"  {m:30s} off-target per recovery {v['off_target_per_recovery']} [{v['ci95'][0]}, {v['ci95'][1]}]  "
                  f"out of spec {v['out_of_spec_total_per_run']}  monitors {v['monitor_wafers_per_recovery']}  repeats {v['repeats']}")
        for k, v in r["paired"].items():
            print(f"  {k:52s} {v['diff']} [{v['ci95'][0]}, {v['ci95'][1]}]")
    elif args.cmd == "demo":
        import functools
        import http.server
        import threading
        import webbrowser

        root = Path(__file__).resolve().parent.parent / "docs" / "demo"
        if not (root / "index.html").exists():
            raise SystemExit("docs/demo is missing. Build it with: python -m fabtriage export --out docs/demo")
        class Quiet(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *a):
                pass

        handler = functools.partial(Quiet, directory=str(root))
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler)
        url = f"http://127.0.0.1:{args.port}/"
        print(f"FabTriage demo (read-only, saved runs): {url}  (Ctrl+C to stop)", flush=True)
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
    elif args.cmd == "export":
        from .export import export

        print(json.dumps(export(Path(args.out), args.live_url), indent=2))
    elif args.cmd == "serve":
        from .server import serve

        serve(args.port, args.host)
    elif args.cmd == "compare":
        rows = []
        for path in sorted(RUNS.glob(f"results_*_{args.split}.json")):
            data = json.loads(path.read_text())
            rows.append((data["method"], data["summary"]))
        keys = ["n", "decision_accuracy", "missed_faults", "needless_holds", "ungrounded_cases",
                "rule_broken_cases", "avg_tool_calls", "avg_measurements", "avg_lot_delay_h", "total_tokens"]
        print("method".ljust(12) + "".join(k[:14].rjust(15) for k in keys))
        for method, s in rows:
            print(method.ljust(12) + "".join(str(s.get(k)).rjust(15) for k in keys))


if __name__ == "__main__":
    main()
