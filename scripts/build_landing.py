"""Build docs/index.html, the project's front page, from saved results.

    python scripts/build_landing.py

Reads the demo data in docs/demo/data and the results in runs/, so rerun it after new runs
and after `python -m fabtriage export`. Every number and chart on the page comes from them.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
U = str(ROOT)
ctx = json.load(open(f"{U}/docs/demo/data/context/pm_shift-1.json"))
diag = json.load(open(f"{U}/docs/demo/data/run/agent/pm_shift-1.json"))["run"]
reca = json.load(open(f"{U}/docs/demo/data/recovery/run/agent/rec_after_pm_shift-1.json"))["run"]
reck = json.load(open(f"{U}/docs/demo/data/recovery/run/keep_recipe/rec_after_pm_shift-1.json"))["run"]
sweep = json.load(open(f"{U}/runs/sweep.json"))
res = {m: json.load(open(f"{U}/runs/results_{m}_holdout3.json"))["rows"] for m in ["agent", "oneshot", "playbook"]}

INK, MUTED, LINE, AMBER, AMBERD, HOLD, REL, SLATE, PAPER, PANEL = "#18262B", "#56666A", "#CBD3D1", "#D99A0B", "#8A6100", "#B93A2E", "#2E7A57", "#3E5A66", "#EDF0EE", "#FAFBFA"
T = 'font-family="Barlow, Helvetica Neue, Arial, sans-serif"'

def spc_chart(W=1100, H=380, big=True):
    P = {"l": 52, "r": 150, "t": 20, "b": 36}
    t0, t1 = ctx["window"]; lo, hi = 480, 522
    x = lambda t: P["l"] + (t - t0) / (t1 - t0) * (W - P["l"] - P["r"])
    y = lambda v: P["t"] + (1 - (v - lo) / (hi - lo)) * (H - P["t"] - P["b"])
    s = [f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="Film thickness on {ctx["chamber"]} over the last 24 hours, with a PM at 63.7 hours and the out-of-spec alarm at 72 hours" {T} style="display:block; min-width: 640px">']
    for v, c, d, lab in [(515, HOLD, "6 4", "515 upper spec"), (485, HOLD, "6 4", "485 lower spec"), (507, AMBER, "2 4", "507 control"), (493, AMBER, "2 4", "493 control"), (500, LINE, "", "500 target")]:
        s.append(f'<line x1="{P["l"]}" x2="{W-P["r"]}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="{c}" stroke-dasharray="{d}" stroke-width="1.2"/>')
        s.append(f'<text x="{W-P["r"]+8}" y="{y(v)+4:.1f}" font-size="13" fill="{MUTED}">{lab}</text>')
    pm = ctx["pm"][0]
    s.append(f'<line x1="{x(pm):.1f}" x2="{x(pm):.1f}" y1="{P["t"]}" y2="{H-P["b"]}" stroke="{SLATE}" stroke-dasharray="4 4"/>')
    s.append(f'<text x="{x(pm)-8:.1f}" y="{P["t"]+14}" font-size="14" fill="{SLATE}" text-anchor="end">PM at {pm} h</text>')
    for p in ctx["points"]:
        if p["chamber"] != ctx["chamber"]:
            s.append(f'<circle cx="{x(p["t"]):.1f}" cy="{y(p["v"]):.1f}" r="3" fill="#AEB9B7"/>')
    mine = [p for p in ctx["points"] if p["chamber"] == ctx["chamber"]]
    pts = " ".join("%.1f,%.1f" % (x(p["t"]), y(p["v"])) for p in mine)
    s.append(f'<polyline fill="none" stroke="{INK}" stroke-width="2" points="{pts}"/>')
    for p in mine:
        s.append(f'<circle cx="{x(p["t"]):.1f}" cy="{y(p["v"]):.1f}" r="4" fill="{INK}"/>')
    a = mine[-1]
    s.append(f'<circle cx="{x(a["t"]):.1f}" cy="{y(a["v"]):.1f}" r="11" fill="none" stroke="{HOLD}" stroke-width="2.5"/>')
    for i, tt in enumerate(range(48, 73, 6)):
        s.append(f'<text x="{x(tt):.1f}" y="{H-12}" font-size="13" fill="{MUTED}" text-anchor="middle">{tt} h</text>')
    for v in (485, 500, 515):
        s.append(f'<text x="{P["l"]-8}" y="{y(v)+4:.1f}" font-size="13" fill="{MUTED}" text-anchor="end">{v}</text>')
    s.append(f'<text x="{P["l"]}" y="{P["t"]-6}" font-size="13" fill="{MUTED}">Å</text>')
    s.append("</svg>")
    return "".join(s)

def rec_chart(W=360, H=180):
    P = {"l": 34, "r": 10, "t": 10, "b": 24}
    A = [l["true_A"] for l in reca["outcome"]["lots"]]; K = [l["true_A"] for l in reck["outcome"]["lots"]]
    lo, hi = 488, 516
    x = lambda i: P["l"] + i / (len(A) - 1) * (W - P["l"] - P["r"])
    y = lambda v: P["t"] + (1 - (v - lo) / (hi - lo)) * (H - P["t"] - P["b"])
    s = [f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="40 production lots after release: agent recipe stays near 500, the old recipe runs thick" {T} style="display:block">']
    for v, c, d in [(515, HOLD, "6 4"), (507, AMBER, "2 4"), (493, AMBER, "2 4"), (500, LINE, "")]:
        s.append(f'<line x1="{P["l"]}" x2="{W-P["r"]}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="{c}" stroke-dasharray="{d}"/>')
    for v in (493, 500, 507, 515):
        s.append(f'<text x="{P["l"]-6}" y="{y(v)+4:.1f}" font-size="11" fill="{MUTED}" text-anchor="end">{v}</text>')
    s.append(f'<polyline fill="none" stroke="#9AA6A4" stroke-width="1.6" points="{" ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(K))}"/>')
    s.append(f'<polyline fill="none" stroke="{INK}" stroke-width="2.2" points="{" ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(A))}"/>')
    for i, v in enumerate(K):
        if abs(v - 500) > 7:
            s.append(f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="2.6" fill="{HOLD}"/>')
    s.append(f'<text x="{P["l"]}" y="{H-6}" font-size="11" fill="{MUTED}">lot 1</text><text x="{W-P["r"]}" y="{H-6}" font-size="11" fill="{MUTED}" text-anchor="end">lot 40</text>')
    s.append("</svg>")
    return "".join(s)

SCEN = [("pm_shift", "Chamber after PM"), ("buildup_drift", "Buildup drift"), ("metrology_error", "Metrology misread"), ("upstream_clean", "Upstream clean"), ("wafer_noise", "One-off wafer"), ("sensor_fault", "Sensor fault"), ("heater_drift", "Heater drift")]

def matrix(W=1100):
    cell, gap, ggap, left, top = 13, 3, 16, 190, 34
    rows = [("agent", "Agent, Muse Spark 1.3"), ("oneshot", "Same model, no tools"), ("playbook", "Fixed playbook")]
    gw = 10 * cell + 9 * gap
    H = top + len(rows) * (cell + 14) + 10
    W = left + 7 * gw + 6 * ggap + 10
    s = [f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="Each square is one of 70 held-out alarms. Filled: right decision. Red outline with a cross: wrong decision." {T} style="display:block; min-width: 880px">']
    for g, (key, lab) in enumerate(SCEN):
        gx = left + g * (gw + ggap)
        s.append(f'<text x="{gx}" y="18" font-size="12.5" fill="{MUTED}">{lab}</text>')
    for r, (m, lab) in enumerate(rows):
        yy = top + r * (cell + 14)
        s.append(f'<text x="0" y="{yy+cell-1}" font-size="14" fill="{INK}" font-weight="{600 if m=="agent" else 400}">{lab}</text>')
        byc = {x["case_id"]: x["decision_correct"] for x in res[m]}
        for g, (key, _) in enumerate(SCEN):
            gx = left + g * (gw + ggap)
            for i, seed in enumerate(range(9, 19)):
                ok = byc[f"{key}-{seed}"]
                cx = gx + i * (cell + gap)
                if ok:
                    s.append(f'<rect x="{cx}" y="{yy}" width="{cell}" height="{cell}" fill="{SLATE if m!="agent" else INK}"/>')
                else:
                    s.append(f'<rect x="{cx+1}" y="{yy+1}" width="{cell-2}" height="{cell-2}" fill="none" stroke="{HOLD}" stroke-width="2"/><path d="M{cx+3} {yy+3} L{cx+cell-3} {yy+cell-3} M{cx+cell-3} {yy+3} L{cx+3} {yy+cell-3}" stroke="{HOLD}" stroke-width="1.6"/>')
    s.append("</svg>")
    return "".join(s)

def sweep_chart(kind, W=520, H=250):
    P = {"l": 44, "r": 120, "t": 14, "b": 30}
    if kind == "diagnosis":
        key, lo, hi, ticks, unit = "decision_accuracy_pct", 40, 100, [40, 60, 80, 100], "%"
        series = [("agent", "Agent", INK, 3, ""), ("oneshot", "No tools", SLATE, 2, "5 3"), ("playbook", "Playbook", AMBERD, 2, "")]
    else:
        key, lo, hi, ticks, unit = "off_target_per_recovery", 0, 8, [0, 2, 4, 6, 8], ""
        series = [("agent", "Agent", INK, 3, ""), ("monitor_rule", "Two-monitor rule", AMBERD, 2, ""), ("oracle", "Noise floor", SLATE, 2, "5 3")]
    data = sweep[kind]
    x = lambda i: P["l"] + i / 3 * (W - P["l"] - P["r"])
    y = lambda v: P["t"] + (1 - (v - lo) / (hi - lo)) * (H - P["t"] - P["b"])
    s = [f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="{kind} across four stress levels" {T} style="display:block; min-width: 440px">']
    for t in ticks:
        s.append(f'<line x1="{P["l"]}" x2="{W-P["r"]}" y1="{y(t):.1f}" y2="{y(t):.1f}" stroke="{LINE}"/><text x="{P["l"]-8}" y="{y(t)+4:.1f}" font-size="12" fill="{MUTED}" text-anchor="end">{t}{unit}</text>')
    for i in range(4):
        s.append(f'<text x="{x(i):.1f}" y="{H-8}" font-size="12" fill="{MUTED}" text-anchor="middle">level {i}</text>')
    labels = []
    for m, lab, col, w, dash in series:
        vals = [v[key] for v in data[m]]
        s.append(f'<polyline fill="none" stroke="{col}" stroke-width="{w}" stroke-dasharray="{dash}" points="{" ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(vals))}"/>')
        for i, v in enumerate(vals):
            s.append(f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="3.5" fill="{col}"/>')
        labels.append([y(vals[-1]) + 4, lab, col])
    labels.sort()
    for i in range(1, len(labels)):
        if labels[i][0] - labels[i - 1][0] < 15:
            labels[i][0] = labels[i - 1][0] + 15
    for yy, lab, col in labels:
        s.append(f'<text x="{x(3)+10:.1f}" y="{yy:.1f}" font-size="13" font-weight="600" fill="{col}">{lab}</text>')
    s.append("</svg>")
    return "".join(s)

HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FabTriage</title>
<meta name="description" content="An agent on Meta Muse Spark that investigates chip fab alarms, cites its evidence, and brings a held chamber back to target.">
<script>if (/[?&]lang=(ko|kr)/.test(location.search)) location.replace("demo/" + location.search);</script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Barlow:wght@400;500;600&family=Barlow+Semi+Condensed:wght@500;600;700&display=swap" rel="stylesheet">
<style>
body{margin:0;background:#EDF0EE}
a{color:#18262B}a:hover{color:#3E5A66}
a:focus-visible{outline:2px solid #D99A0B;outline-offset:3px}
@media (max-width:640px){h1{font-size:40px !important}}
</style>
</head>
<body>
"""
TAIL = "</body>\n</html>\n"
HD = "font-family: 'Barlow Semi Condensed', 'Arial Narrow', sans-serif"
BD = "font-family: Barlow, 'Helvetica Neue', Arial, sans-serif"

steps = [
    ("Alarm", "LOT-1239 reads 516.70 Å on DEP01-B, above the 515 Å spec limit. Something has to be decided: hold it or let it go."),
    ("Investigation", "Muse Spark picks its own checks: the lot's route, all four chambers side by side, the PM log, the thickness trend, a commonality test, the heater sensors. Ten tool calls, every result numbered E1 to E10."),
    ("Verdict", "Hold the lot and the chamber: DEP01-B came back from PM about 15 Å thick. Every claim cites its evidence, and plain code checks every number before an engineer sees it."),
    ("Recovery", "The held chamber is brought back: two monitor wafers, a recipe 2.9% shorter, and 40 production lots inside the limits. Keeping the old recipe would have sent 11 of them off target."),
]

def main_page():
    out = [HEAD]
    out.append(f'''<div style="{BD}; color: {INK}; background: {PAPER}; min-height: 100%;">
<div style="max-width: 1180px; margin: 0 auto; padding: 40px 32px 80px; display: flex; flex-direction: column; gap: 72px">
<header style="display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: 16px">
<div style="{HD}; font-weight: 700; font-size: 24px">FabTriage</div>
<nav style="display: flex; gap: 28px; font-size: 16px; flex-wrap: wrap"><a href="demo/">Open the console</a><a href="https://github.com/yhwang55/fabtriage">Code and results</a><a href="demo/?lang=ko">한국어</a></nav>
</header>
<section style="display: flex; flex-direction: column; gap: 28px">
<h1 style="{HD}; font-weight: 700; font-size: 64px; line-height: 1.02; margin: 0; max-width: 16ch">When a chip fab alarm fires, the agent finds out why and proves it.</h1>
<p style="font-size: 20px; line-height: 1.5; margin: 0; max-width: 60ch; color: {MUTED}">FabTriage investigates film-thickness and sensor alarms in a simulated CVD deposition area, proposes what to hold and what to release with cited evidence, and then brings a held chamber back to target. Built on Meta's Muse Spark.</p>
<figure style="margin: 0; background: {PANEL}; padding: 28px 28px 16px; display: flex; flex-direction: column; gap: 12px">
<figcaption style="display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: 12px"><span style="{HD}; font-weight: 600; font-size: 22px">DEP01-B, wafer means over the last 24 hours</span><span style="{HD}; font-weight: 700; font-size: 44px; color: {HOLD}">516.70 Å</span></figcaption>
<div style="overflow-x: auto; direction: rtl"><div style="direction: ltr; width: max(100%, 640px)">{spc_chart()}</div></div>
<p style="margin: 0; font-size: 14px; color: {MUTED}">Black: the alarm chamber. Grey: the other three chambers. Real data from alarm ALM-13183 in the demo.</p>
</figure>
</section>
<section style="display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 32px">''')
    for i, (h, body) in enumerate(steps):
        extra = f'<div style="margin-top: 8px">{rec_chart()}</div><p style="margin: 0; font-size: 13px; color: {MUTED}">Black: agent recipe. Grey: old recipe, red dots off target.</p>' if h == "Recovery" else ""
        out.append(f'''<div style="display: flex; flex-direction: column; gap: 10px; border-top: 3px solid {INK if i < 3 else REL}; padding-top: 14px">
<div style="{HD}; font-weight: 600; font-size: 15px; color: {MUTED}">Step {i+1}</div>
<h2 style="{HD}; font-weight: 700; font-size: 30px; margin: 0">{h}</h2>
<p style="margin: 0; font-size: 16px; line-height: 1.5">{body}</p>{extra}
</div>''')
    out.append(f'''</section>
<section style="display: flex; flex-direction: column; gap: 22px">
<h2 style="{HD}; font-weight: 700; font-size: 40px; margin: 0">70 alarms nobody had looked at</h2>
<p style="margin: 0; font-size: 18px; line-height: 1.5; max-width: 66ch">Each square is one held-out alarm. The agent made the right call on all 70, in each of three runs. A fixed rulebook missed 15, most of them upstream clean problems and real heater changes it mistook for something else. The analysis plan was committed before the run.</p>
<div style="background: {PANEL}; padding: 24px; overflow-x: auto">{matrix()}</div>
<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 28px">
<div><div style="{HD}; font-weight: 700; font-size: 44px">100%</div><p style="margin: 4px 0 0; font-size: 16px; line-height: 1.45">right decisions, 95% interval 94.8 to 100. The fixed playbook: 78.6%.</p></div>
<div><div style="{HD}; font-weight: 700; font-size: 44px">0 of 70</div><p style="margin: 4px 0 0; font-size: 16px; line-height: 1.45">dispositions broke a safety rule. Without the verifier, 19 did.</p></div>
<div><div style="{HD}; font-weight: 700; font-size: 44px">0.23</div><p style="margin: 4px 0 0; font-size: 16px; line-height: 1.45">off-target lots per recovery over 50 recoveries. The best guide rule: 1.86.</p></div>
</div>
</section>
<section style="display: flex; flex-direction: column; gap: 22px">
<h2 style="{HD}; font-weight: 700; font-size: 40px; margin: 0">Where it breaks</h2>
<p style="margin: 0; font-size: 18px; line-height: 1.5; max-width: 66ch">Faults keep their size while the evidence gets weaker: noisier film, fewer measured lots, faults that began more recently. The agent holds up through level 2. At level 3 its lead is gone, but it fails safe: no missed faults, more needless holds.</p>
<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 32px">
<figure style="margin: 0; display: flex; flex-direction: column; gap: 8px"><figcaption style="{HD}; font-weight: 600; font-size: 20px">Diagnosis, right decisions</figcaption><div style="overflow-x: auto">{sweep_chart("diagnosis")}</div></figure>
<figure style="margin: 0; display: flex; flex-direction: column; gap: 8px"><figcaption style="{HD}; font-weight: 600; font-size: 20px">Recovery, off-target lots per recovery</figcaption><div style="overflow-x: auto">{sweep_chart("recovery")}</div></figure>
</div>
</section>
<section style="display: flex; flex-wrap: wrap; gap: 24px; align-items: center; justify-content: space-between; border-top: 1px solid {LINE}; padding-top: 28px">
<p style="margin: 0; font-size: 16px; line-height: 1.5; max-width: 62ch; color: {MUTED}">A simulated fab, not production data. Scenarios follow public fab case studies and practitioner input. The recovery idea comes from Prof. Jang (The Catholic University of Korea). Built by Yoon Hwang for the Meta Global AI Developer Hackathon.</p>
<a href="demo/" style="{HD}; font-weight: 600; font-size: 20px; color: {PANEL}; background: {INK}; padding: 14px 24px; text-decoration: none; min-height: 44px; box-sizing: border-box">Open the console</a>
</section>
</div></div>''')
    out.append(TAIL)
    return "".join(out)


if __name__ == "__main__":
    (ROOT / "docs" / "index.html").write_text(main_page())
    print("wrote docs/index.html")
