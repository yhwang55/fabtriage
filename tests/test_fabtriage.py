import json
from types import SimpleNamespace

import pytest

from fabtriage import agent, evaluate, sim, verify
from fabtriage.baselines import playbook
from fabtriage.tools import Investigation


def test_simulator_is_deterministic():
    a, b = sim.load("pm_shift-1"), sim.load("pm_shift-1")
    assert a.alarm == b.alarm
    assert [lot["measurement"] for lot in a.lots] == [lot["measurement"] for lot in b.lots]


def test_benchmark_splits_do_not_overlap():
    assert not set(sim.benchmark("dev")) & set(sim.benchmark("holdout"))
    assert len(sim.benchmark("all")) == len(sim.SCENARIOS) * 8
    assert not set(sim.benchmark("holdout2")) & set(sim.benchmark("dev") + sim.benchmark("holdout"))


@pytest.mark.parametrize("case_id", sim.benchmark("all"))
def test_tools_never_leak_the_truth(case_id, tmp_path):
    case = sim.load(case_id)
    inv = Investigation(case, tmp_path / case_id)
    c, lot = case.alarm["chamber"], case.alarm["lot_id"]
    calls = [
        ("get_alarm", {}),
        ("get_lot_history", {"lot_id": lot}),
        ("get_chamber_summary", {}),
        ("get_trend", {"chamber": c, "signal": "thickness"}),
        ("get_trend", {"chamber": c, "signal": "heater_temp_C"}),
        ("run_commonality", {}),
        ("query_lots", {"window_hours": 24}),
        ("get_fdc_summary", {"chamber": c}),
        ("get_pm_log", {}),
        ("request_measurement", {"lot_id": lot, "met_tool": "MET01"}),
        ("get_wafer_map", {"lot_id": lot}),
    ]
    for name, args in calls:
        text = json.dumps(inv.call(name, args))
        for secret in ("_true_sites", "truth", "hidden", "confounder", "scenario", case.scenario):
            assert secret not in text, (name, secret)


def test_ungrounded_number_is_refused(tmp_path):
    inv = Investigation(sim.load("pm_shift-3"), tmp_path)
    a = inv.call("get_alarm", {})
    s = inv.call("get_chamber_summary", {})
    c = a["alarm"]["chamber"]
    t = inv.call("get_trend", {"chamber": c, "signal": "thickness"})
    lot = a["alarm"]["lot_id"]
    bad = {
        "cause": "chamber",
        "actions": [{"type": "hold_lot", "target": lot}, {"type": "hold_chamber", "target": c}],
        "claims": [
            {"evidence_id": a["evidence_id"], "statement": f"{c} read 999.9 A."},
            {"evidence_id": t["evidence_id"], "statement": f"Last value {t['last_value']}."},
        ],
        "summary": "x",
    }
    r = inv.call("submit_disposition", bad)
    assert r["accepted"] is False
    assert any("999.9" in p for p in r["problems"])
    good = dict(bad)
    good["claims"] = [
        {"evidence_id": a["evidence_id"], "statement": f"{c} alarm value {a['alarm']['value']}."},
        {"evidence_id": s["evidence_id"], "statement": f"{c} 24 hour mean {s['chambers'][c]['mean_A']}."},
        {"evidence_id": t["evidence_id"], "statement": f"Last value {t['last_value']}."},
    ]
    r = inv.call("submit_disposition", good)
    assert r["accepted"] is True, r


def test_oos_lot_cannot_be_released_without_remeasure(tmp_path):
    case = sim.load("metrology_error-1")
    assert case.alarm["type"] == "OOS"
    inv = Investigation(case, tmp_path)
    a = inv.call("get_alarm", {})
    s = inv.call("get_chamber_summary", {})
    r = inv.call(
        "submit_disposition",
        {
            "cause": "metrology",
            "actions": [{"type": "release_lot", "target": a["alarm"]["lot_id"]}],
            "claims": [
                {"evidence_id": a["evidence_id"], "statement": "Alarm on MET02."},
                {"evidence_id": s["evidence_id"], "statement": "Chambers look normal."},
            ],
            "summary": "x",
        },
    )
    assert not r["accepted"]
    assert any("re-measurement" in p for p in r["problems"])


def test_three_refusals_go_to_an_engineer(tmp_path):
    inv = Investigation(sim.load("wafer_noise-1"), tmp_path)
    for _ in range(3):
        r = inv.call("submit_disposition", {"cause": "noise", "actions": [], "claims": [], "summary": ""})
    assert r["status"] == "needs_engineer"
    assert inv.call("get_alarm", {})["error"].startswith("investigation is closed")


def test_playbook_passes_verification_everywhere(tmp_path):
    for cid in sim.benchmark("all"):
        inv = Investigation(sim.load(cid), tmp_path / cid)
        playbook(inv)
        assert inv.status == "awaiting_signoff", (cid, inv.refusals)


def test_number_extraction_ignores_ids():
    assert verify.numbers_in("LOT-1239 on DEP01-A via MET02 cited E4 read 517.67") == ["517.67"]
    assert verify.grounded("517.7", [517.67])
    assert not verify.grounded("517.9", [517.67])
    assert verify.numbers_in("slope 1.2 A per 100 wafers") == ["1.2"]


# ------------------------------------------------------------------ fake models


class _Script:
    """Plays a fixed investigation, reading evidence ids from the tool outputs it gets back."""

    def __init__(self):
        self.step = 0
        self.seen = []

    def next_call(self, outputs, alarm):
        self.step += 1
        c, lot = alarm["chamber"], alarm["lot_id"]
        if self.step == 1:
            return "get_alarm", {}
        if self.step == 2:
            return "get_chamber_summary", {"window_hours": 24}
        if self.step == 3:
            return "get_trend", {"chamber": c, "signal": "thickness"}
        if self.step == 4:  # first try invents a number
            return "submit_disposition", {
                "cause": "chamber",
                "actions": [{"type": "hold_lot", "target": lot}],
                "claims": [{"evidence_id": "E1", "statement": "Value 123.45."}],
                "summary": "x",
            }
        a, s, t = outputs[0], outputs[1], outputs[2]
        return "submit_disposition", {
            "cause": "chamber",
            "actions": [{"type": "hold_lot", "target": lot}, {"type": "hold_chamber", "target": c}],
            "claims": [
                {"evidence_id": a["evidence_id"], "statement": f"Alarm value {a['alarm']['value']}."},
                {"evidence_id": s["evidence_id"], "statement": f"{c} mean {s['chambers'][c]['mean_A']}."},
                {"evidence_id": t["evidence_id"], "statement": f"Last value {t['last_value']}."},
            ],
            "summary": "Chamber is off after PM.",
        }


def _fake_responses(alarm):
    script = _Script()

    def create(**kw):
        outputs = [json.loads(m["output"]) for m in kw["input"] if isinstance(m, dict) and m.get("type") == "function_call_output"]
        name, args = script.next_call(outputs, alarm)
        call = SimpleNamespace(type="function_call", name=name, arguments=json.dumps(args), call_id=f"c{script.step}")
        return SimpleNamespace(output=[call], output_text="", usage=SimpleNamespace(total_tokens=100))

    return SimpleNamespace(responses=SimpleNamespace(create=create))


def _fake_chat(alarm):
    script = _Script()

    def create(**kw):
        outputs = [json.loads(m["content"]) for m in kw["messages"] if m.get("role") == "tool"]
        name, args = script.next_call(outputs, alarm)
        tc = SimpleNamespace(id=f"c{script.step}", function=SimpleNamespace(name=name, arguments=json.dumps(args)))
        msg = SimpleNamespace(content="thinking", tool_calls=[tc])
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=SimpleNamespace(total_tokens=50))

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


@pytest.mark.parametrize("backend,fake", [("meta", _fake_responses), ("baseten", _fake_chat)])
def test_agent_loop_recovers_from_a_refusal(backend, fake, tmp_path):
    case = sim.load("pm_shift-3")
    inv = Investigation(case, tmp_path)
    out = agent.run_agent(inv, fake(case.alarm), backend=backend)
    assert inv.status == "awaiting_signoff"
    assert inv.tries == 2 and len(inv.refusals) == 1
    assert out["tokens"] > 0
    row = evaluate.score(case, inv)
    assert row["decision_correct"] and row["cause_correct"]


def test_verifier_off_accepts_but_records_problems(tmp_path):
    case = sim.load("metrology_error-1")
    inv = Investigation(case, tmp_path)
    inv.verify_enabled = False
    a = inv.call("get_alarm", {})
    r = inv.call(
        "submit_disposition",
        {
            "cause": "metrology",
            "actions": [{"type": "release_lot", "target": a["alarm"]["lot_id"]}],
            "claims": [{"evidence_id": a["evidence_id"], "statement": "Read 999.1."}],
            "summary": "x",
        },
    )
    assert r["accepted"]
    row = evaluate.score(case, inv)
    assert row["ungrounded_claims"] and row["playbook_rule_broken"]


def test_oneshot_with_fake_model(tmp_path):
    from fabtriage.oneshot import run_oneshot

    case = sim.load("pm_shift-3")
    inv = Investigation(case, tmp_path)
    c, lot = case.alarm["chamber"], case.alarm["lot_id"]
    reply = json.dumps({
        "cause": "chamber",
        "actions": [{"type": "hold_lot", "target": lot}, {"type": "hold_chamber", "target": c}],
        "claims": [{"evidence_id": "E1", "statement": f"Alarm value {case.alarm['value']}."}],
        "summary": "x",
    })
    client = SimpleNamespace(responses=SimpleNamespace(create=lambda **kw: SimpleNamespace(output_text="Here: " + reply, usage=SimpleNamespace(total_tokens=10))))
    out = run_oneshot(inv, client, "meta")
    assert inv.status == "awaiting_signoff" and out["tokens"] == 10
    row = evaluate.score(case, inv)
    assert row["decision_correct"] and not row["ungrounded_claims"]
    assert row["playbook_rule_broken"]  # one claim only, and no chamber comparison cited


def test_voice_multipart_and_guards(monkeypatch):
    from fabtriage import voice

    body, kind = voice.multipart({"request": '{"model": "m"}'}, {"audio": ("n.wav", b"RIFFxx", "audio/wav")})
    boundary = kind.split("boundary=")[1]
    assert body.count(boundary.encode()) == 3 and b'name="audio"; filename="n.wav"' in body
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    assert "error" in voice.transcribe(b"RIFF")
    monkeypatch.setenv("MODEL_API_KEY", "k")
    assert "error" in voice.transcribe(b"not a wav")


def test_repeats_and_impact(tmp_path):
    from fabtriage import impact

    out = evaluate.run_repeats("playbook", "holdout", tmp_path, 2)
    assert out["repeats"] == 2 and out["mean_std"]["decision_accuracy"]["std"] == 0.0
    assert (tmp_path / "repeats" / "r2" / "playbook").exists()
    evaluate.run_split("always_hold", "holdout", tmp_path)
    t = impact.table(tmp_path, "holdout")
    assert t["methods"]["always_hold"]["engineer_hours"] == 250.0
    assert t["methods"]["playbook"]["engineer_hours"] < 250.0


# ------------------------------------------------------------------ recovery after PM


@pytest.mark.parametrize("case_id", __import__("fabtriage.recovery", fromlist=["x"]).benchmark("all"))
def test_recovery_tools_never_leak_the_truth(case_id):
    from fabtriage import recovery as R

    job = R.RecoveryJob(R.load(case_id))
    job.call("get_recovery_brief", {})
    job.call("get_chamber_history", {})
    job.call("get_metrology_matching", {})
    m = job.call("run_monitor_wafer", {"time_s": job.case.pre_pm_time_s})
    job.call("estimate_recipe", {"monitor_evidence_ids": [m["evidence_id"]]})
    text = json.dumps(job.trace)
    names = [job.case.scenario] if "_" in job.case.scenario else []  # "seasoning" is also a PM record field
    for secret in ("post_frac", "pre_frac", "season\"", "hidden", "truth", "scenario", *names):
        assert secret not in text, secret


def test_recovery_splits_and_determinism():
    from fabtriage import recovery as R

    assert not set(R.benchmark("dev")) & set(R.benchmark("holdout"))
    a = R.run_out(R.load("rec_seasoning-1"), 61.0, 0.3, 0.0, 2)
    b = R.run_out(R.generate("seasoning", 1), 61.0, 0.3, 0.0, 2)
    assert a == b


def test_recovery_verifier_rules():
    from fabtriage import recovery as R

    job = R.RecoveryJob(R.load("rec_post_pm_reset-1"))
    b = job.call("get_recovery_brief", {})
    h = job.call("get_chamber_history", {})
    claims = [{"evidence_id": b["evidence_id"], "statement": "Wet clean done."}, {"evidence_id": h["evidence_id"], "statement": "History read."}]
    r = job.call("release_chamber", {"time_s": job.case.pre_pm_time_s, "claims": claims, "summary": "x"})
    assert not r["accepted"] and any("monitor wafer" in p for p in r["problems"])
    r = job.call("release_chamber", {"time_s": 61.37, "claims": claims, "summary": "x"})
    assert any("not from evidence" in p for p in r["problems"])
    assert job.status == "running"
    m = job.call("run_monitor_wafer", {"time_s": job.case.pre_pm_time_s, "met_tool": "MET01"})
    e = job.call("estimate_recipe", {"monitor_evidence_ids": [m["evidence_id"]]})
    r = job.call("release_chamber", {"time_s": e["recipe_time_s_for_500A"], "claims": claims, "summary": "x"})
    assert r["accepted"], r
    row, out = R.score(job)
    assert row["status"] == "released" and len(out["lots"]) == R.N_LOTS


def test_recovery_offset_must_come_from_matching():
    from fabtriage import recovery as R

    job = R.RecoveryJob(R.load("rec_metrology_bias-1"))
    m = job.call("run_monitor_wafer", {"time_s": 61})
    r = job.call("estimate_recipe", {"monitor_evidence_ids": [m["evidence_id"]], "met_offsets_A": {"MET02": 5}})
    assert "error" in r
    mm = job.call("get_metrology_matching", {})
    r = job.call("estimate_recipe", {"monitor_evidence_ids": [m["evidence_id"]], "met_offsets_A": {"MET02": mm["MET02_minus_MET01_A"]}})
    assert "error" not in r


def test_recovery_agent_loop_with_fake_model(tmp_path):
    from fabtriage import recovery as R, recovery_eval as RE

    case = R.load("rec_no_shift-1")
    step = {"n": 0}

    def create(**kw):
        step["n"] += 1
        assert "recovery mode" in kw["instructions"] and any(t["name"] == "release_chamber" for t in kw["tools"])
        outs = [json.loads(m["output"]) for m in kw["input"] if isinstance(m, dict) and m.get("type") == "function_call_output"]
        if step["n"] == 1:
            name, args = "get_recovery_brief", {}
        elif step["n"] == 2:
            name, args = "get_chamber_history", {}
        else:
            name, args = "release_chamber", {
                "time_s": case.pre_pm_time_s,
                "claims": [{"evidence_id": outs[0]["evidence_id"], "statement": f"PM did not open the chamber; pre-PM time {case.pre_pm_time_s} s."},
                           {"evidence_id": outs[1]["evidence_id"], "statement": "Previous cycle was stable."}],
                "summary": "Keep the recipe.",
            }
        call = SimpleNamespace(type="function_call", name=name, arguments=json.dumps(args), call_id=f"c{step['n']}")
        return SimpleNamespace(output=[call], output_text="", usage=SimpleNamespace(total_tokens=10))

    client = SimpleNamespace(responses=SimpleNamespace(create=create))
    row = RE.run_one("agent", "rec_no_shift-1", tmp_path, client, "meta")
    assert row["status"] == "released" and row["recipe_change_pct"] == 0.0 and row["off_target_lots"] == 0
    for m in ("keep_recipe", "reset_recipe", "monitor_rule"):
        RE.run_split(m, "holdout", tmp_path)
    res = RE.load_results(tmp_path, "holdout")
    assert {"keep_recipe", "reset_recipe", "monitor_rule"} <= set(res)
