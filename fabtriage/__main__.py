"""Command line.

    python -m fabtriage cases [--split dev]
    python -m fabtriage eval --method playbook --split dev
    python -m fabtriage eval --method agent --split dev --backend meta --limit 3
    python -m fabtriage run --case pm_shift-1 --method agent
    python -m fabtriage compare --split dev
    python -m fabtriage serve            # the console at http://127.0.0.1:8770
"""

from __future__ import annotations

import argparse
import json
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
    c.add_argument("--split", default="all", choices=["dev", "holdout", "holdout2", "all"])
    e = sub.add_parser("eval")
    e.add_argument("--method", required=True, choices=["agent", "agent_noverify", "oneshot", "playbook", "always_hold"])
    e.add_argument("--split", default="dev", choices=["dev", "holdout", "holdout2", "all"])
    e.add_argument("--backend", default="meta", choices=["meta", "baseten"])
    e.add_argument("--limit", type=int)
    e.add_argument("--only", nargs="*", help="scenario name prefixes, e.g. pm_shift heater_drift")
    e.add_argument("--repeats", type=int, default=1, help="run the split this many times and report mean and spread")
    r = sub.add_parser("run")
    r.add_argument("--case", required=True)
    r.add_argument("--method", default="agent", choices=["agent", "agent_noverify", "oneshot", "playbook", "always_hold"])
    r.add_argument("--backend", default="meta", choices=["meta", "baseten"])
    rs = sub.add_parser("rescore", help="rebuild a results file from saved runs")
    rs.add_argument("--method", required=True, choices=["agent", "agent_noverify", "oneshot", "playbook", "always_hold"])
    rs.add_argument("--split", default="dev", choices=["dev", "holdout", "holdout2", "all"])
    im = sub.add_parser("impact", help="per-100-alarm impact under stated assumptions")
    im.add_argument("--split", default="dev", choices=["dev", "holdout", "holdout2", "all"])
    ex = sub.add_parser("export", help="write the console as a static read-only site")
    ex.add_argument("--out", default="docs/demo")
    sv = sub.add_parser("serve")
    sv.add_argument("--port", type=int, default=8770)
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
        out = evaluate.run_repeats(args.method, args.split, RUNS, args.repeats, client, args.backend, sam)
        print(json.dumps({k: out[k] for k in ("mean_std", "cases_always_right", "cases_sometimes_wrong")}, indent=2))
    elif args.cmd == "eval":
        client, sam = _clients(args.method, args.backend)
        result = evaluate.run_split(
            args.method, args.split, RUNS, client, args.backend, args.limit, args.only, sam_client=sam
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
    elif args.cmd == "export":
        from .export import export

        print(json.dumps(export(Path(args.out)), indent=2))
    elif args.cmd == "serve":
        from .server import serve

        serve(args.port)
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
