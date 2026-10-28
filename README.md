# FabTriage

**An agent that investigates semiconductor fab alarms and proposes what to do about them, with every claim checked against the evidence before an engineer signs off.**

Built during the Meta Global AI Developer Hackathon (Oct 26 to Nov 4, 2026). Everything in this repository was written during the event.

## The problem

When a metrology or sensor alarm fires in a fab, an engineer has to work out why before the lot and the equipment can move again. Was it the deposition chamber, the measurement tool, the step before, a one-off wafer, or a broken sensor? The standard answer on the floor is to hold everything and look, which costs hours of lot delay and stops good chambers. A fixed rule-based playbook is faster but breaks on the cases that don't fit its thresholds.

FabTriage does the investigation the way an engineer would: it forms hypotheses, pulls the evidence that separates them, and files a disposition (root cause, actions, cited evidence) for sign-off.

## How it works

```
alarm ──> Muse Spark agent ──picks one tool per turn──> investigation tools (plain code)
                 ^                                           │ every result gets an evidence id
                 └────────────── result ─────────────────────┘
                 │
                 └──> submit_disposition ──> verification layer (plain code) ──> engineer sign-off
                                                  │ refused: problems go back to the agent
                                                  └ 3 refusals: goes to an engineer
```

- **Virtual fab** (`fabtriage/sim.py`): CLEAN (2 tools) → CVD DEP (4 chambers on 2 tools) → MET (2 tools). 72 hours of history, about half the lots sampled at 49 sites, FDC sensors on every run, chamber buildup drift, PM resets, run-to-run compensation.
- **Tools** (`fabtriage/tools.py`): alarm, lot history, lot table query, chamber box-plot summary, trends, commonality analysis (ANOVA per step), FDC summary, PM log, re-measurement (costs lot delay), and a wafer map segmented by **SAM 3.1**. All numbers are computed in code; the model decides what to look at.
- **Verification** (`fabtriage/verify.py`): runs inside `submit_disposition`, so the agent can't skip it. Every claim must cite an evidence id and every number in it must appear in that evidence. Playbook rules apply too, for example an out-of-spec lot can't be released without an in-spec re-measurement. It never sees the ground truth.
- **Models**: Muse Spark 1.3 (Meta Model API) runs the agent; SAM 3.1 reads wafer maps; Muse Spark Open on Baseten runs batch benchmarks.

## Benchmark

7 scenario types × 6 seeds = 42 labeled cases. Seeds 1 to 4 are the dev set (28 cases); seeds 5 and 6 are held out (14 cases) and only run for the final comparison.

| Scenario | What happened | Correct response |
|---|---|---|
| pm_shift | chamber came back from PM running off-target | hold lot + chamber |
| buildup_drift | chamber overdue for PM, film drifting up, thick at the edge | hold lot + chamber |
| metrology_error | MET02 misreads | re-measure, release |
| upstream_clean | CLN02 problem shows up on every chamber | hold lot, escalate CLN02 |
| wafer_noise | one wafer out of control, chamber fine | release |
| sensor_fault | heater sensor reads high, film fine | flag sensor, release |
| heater_drift | heater really runs hot, film affected | hold lot + chamber |

About half the cases carry a confounder (a routine PM on the alarm chamber, the alarm wafer routed through the suspect tool, and so on).

Success criteria, fixed before building the agent:

- cause and decision accuracy on the held-out set above the fixed playbook
- zero missed real faults
- fewer needless holds than "always hold"
- 100% of accepted claims grounded in tool output (enforced by the verifier)
- cost: tool calls, re-measurements (lot delay), tokens

Baselines on the held-out set (14 cases):

| method | cause acc. | decision acc. | missed faults | needless holds | avg tool calls | avg re-measures |
|---|---|---|---|---|---|---|
| always_hold | 0.43 | 0.43 | 0 | 8 | 4.0 | 0.0 |
| playbook | 0.86 | 0.86 | 2 | 0 | 7.4 | 0.7 |
| agent | *final run* | | | | | |

## Run it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # add MODEL_API_KEY (and BASETEN_API_KEY for batch runs)
python -m pytest -q           # no API calls

python -m fabtriage cases --split dev
python -m fabtriage eval --method playbook --split dev
python -m fabtriage run  --case pm_shift-1 --method agent              # one case, Muse Spark
python -m fabtriage eval --method agent --split dev --limit 3          # a few cases first
python -m fabtriage eval --method agent --split dev --backend baseten  # Muse Spark Open
python -m fabtriage compare --split dev
```

Each run writes `runs/<method>/<case>/run.json` with the full trace, refusals, costs and the score.

## Scope note

This is a simplified, simulated fab. Process numbers are illustrative, not from any real fab. The scenarios follow failure modes that practicing fab data scientists described, but the simulator is not calibrated to production data.
