"""Export the console as a static, read-only site (for GitHub Pages or any static host).

    python -m fabtriage export --out docs/demo

Everything the console shows comes from saved runs, so the export is the same app with the
API answered by JSON files. Live runs and sign-off are local-only.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from . import server, sim
from .sources import SOURCES


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, default=str, separators=(",", ":")))


def export(out: Path) -> dict:
    out = Path(out)
    html = (server.WEB / "index.html").read_text()
    html = html.replace("<script>", "<script>window.FABTRIAGE_STATIC = true;</script>\n<script>", 1)
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(html)
    (out / ".nojekyll").write_text("")

    cases = server.cases()
    for c in cases:  # nothing runs live in the static site
        for r in c["runs"].values():
            r["live"] = False
    _write(out / "data" / "cases.json", {"cases": cases, "live_enabled": False})
    _write(out / "data" / "benchmark.json", server.benchmark())

    n_runs = n_maps = 0
    for cid in sim.benchmark("all"):
        _write(out / "data" / "context" / f"{cid}.json", server.context(cid))
        alarm = sim.load(cid).alarm
        png = server.wafer_png(cid, alarm["lot_id"])
        if png:
            (out / "wafer").mkdir(parents=True, exist_ok=True)
            (out / "wafer" / f"{cid}.png").write_bytes(png)
        scenario = cid.rsplit("-", 1)[0]
        for m in server.METHODS:
            run = server._read_run(m, cid)
            if not run:
                continue
            run.pop("live", None)
            _write(out / "data" / "run" / m / f"{cid}.json", {"run": run, "live": False, "sources": SOURCES.get(scenario)})
            n_runs += 1
            maps = server.RUNS / m / cid / "maps"
            if maps.exists():
                for f in maps.glob("*.png"):
                    dest = out / "maps" / m / cid / f.name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(f, dest)
                    n_maps += 1
    from . import recovery as R

    rec = server.recovery_cases()
    _write(out / "data" / "recovery" / "cases.json", {"cases": rec})
    n_rec = 0
    for cid in R.all_ids():
        for m in server.REC_METHODS:
            run = server.recovery_run(m, cid)
            if run:
                run.pop("live", None)
                _write(out / "data" / "recovery" / "run" / m / f"{cid}.json", {"run": run})
                n_rec += 1
    return {"out": str(out), "cases": len(cases), "runs": n_runs, "maps": n_maps, "recovery_runs": n_rec}
