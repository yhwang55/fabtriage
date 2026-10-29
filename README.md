# FabTriage

**An agent that investigates semiconductor fab alarms and proposes what to do about them, with every claim checked against the evidence before an engineer signs off.**

**Live demo (read-only, built from saved runs): https://yhwang55.github.io/fabtriage/**

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
- **Models**: Muse Spark 1.3 (Meta Model API) runs the agent; SAM 3.1 reads wafer maps; Muse Voice Transcribe turns spoken sign-off notes into text; Muse Spark Open on Baseten runs the same agent on open weights.

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

About half the cases carry a confounder (a routine PM on the alarm chamber, the alarm wafer routed through the suspect tool, and so on). Each scenario is tied to public sources and practitioner input in [docs/SCENARIOS.md](docs/SCENARIOS.md).

Success criteria, fixed before building the agent:

- cause and decision accuracy on the held-out set above the fixed playbook
- zero missed real faults
- fewer needless holds than "always hold"
- 100% of accepted claims grounded in tool output (enforced by the verifier)
- cost: tool calls, re-measurements (lot delay), tokens

## Results

Every method runs on the same alarms, through the same tools and the same verifier. Decision accuracy means every required action was taken and no forbidden one (for example, releasing a lot from a faulty chamber).

**How the evaluation went.** The development set (28 cases) was used while building the agent. The first held-out set (seeds 5 and 6, 14 cases) was run once. We read its one failure, added one line of process knowledge to the agent, and checked that version on a second held-out set (seeds 7 and 8, 14 cases) that nobody had looked at. The agent runs three times on each held-out set to show run-to-run spread.

### Fresh held-out set, after the fix (14 cases)

| method | right decision | missed real faults | needless holds | tool calls | re-measures | lot delay (h) |
|---|---|---|---|---|---|---|
| **Agent, Muse Spark 1.3 (3 runs)** | **100% ± 0** | **0** | **0** | 10.3 | 0.79 | 1.18 |
| Agent, Muse Spark Open on Baseten | 100% | 0 | 0 | 14.1 | 1.07 | 1.61 |
| Agent without the verifier | 100% | 0 | 0 | 9.8 | 0.57 | 0.86 |
| Same model, one shot, no tools | 93% | 0 | 1 | 10 (fixed) | 0 | 0 |
| Fixed playbook | 71% | 3 | 1 | 7.4 | 0.71 | 1.07 |
| Always hold | 43% | 0 | 8 | 4.0 | 0 | 0 |

### First held-out set, before the fix (14 cases)

| method | right decision | missed real faults | needless holds | tool calls | re-measures |
|---|---|---|---|---|---|
| **Agent, Muse Spark 1.3 (3 runs)** | **97.6% ± 4.1** | **0** | 0.3 | 9.7 | 0.64 |
| Agent, Muse Spark Open on Baseten | 93% | 0 | 1 | 14.6 | 1.21 |
| Agent without the verifier | 100% | 0 | 0 | 9.8 | 0.71 |
| Same model, one shot, no tools | 71% | 0 | 4 | 10 (fixed) | 0 |
| Fixed playbook | 86% | 2 | 0 | 7.4 | 0.71 |
| Always hold | 43% | 0 | 8 | 4.0 | 0 |

Development set (28 cases): agent 100%, fixed playbook 86% (2 missed faults), always hold 43%.

### The one failure, and the fix

`sensor_fault-6` failed in one of three runs (and in the Muse Spark Open run). The heater sensor read 13 °C high but the film was fine. The agent re-measured the alarm lot, found it about 6 Å *thinner* than the chamber's usual level (still inside control limits), and read that as proof of a real heater change. A hotter heater deposits faster, so a real change would have made the film thicker. We added one line of process knowledge to the agent's instructions: deposition rate rises with temperature, so film that stays in control or moves the other way points to the sensor ([source](docs/SCENARIOS.md#heater-drift)). On the fresh held-out set the sensor and heater cases were right in all six runs.

### What the comparisons show

- **Investigating beats answering.** The same model given a fixed evidence pack and one shot at the answer was right 71% and 93% of the time on the two held-out sets, and broke a playbook rule in 4 of those 28 cases (on the development set, it released out-of-spec lots without a confirming re-measurement five times). The agent asks for a re-measurement when the answer depends on it.
- **The verifier keeps evidence complete; it did not change accuracy here.** Without it the agent made the same decisions, but 1 of 14 and 4 of 14 dispositions would have reached the engineer missing evidence the playbook requires (for example, holding a chamber without citing a comparison to the other chambers). Muse Spark never cited a number that was not in its tool output.
- **Open weights work too.** Muse Spark Open on Baseten matched the accuracy on the fresh set but used about 40% more tool calls and re-measurements.
- **The cost.** The agent does slightly more re-measuring than the playbook on the fresh set (1.18 vs 1.07 lot-hours per alarm) in exchange for zero missed faults instead of three.

### Per 100 alarms (fresh held-out set, illustrative)

| method | engineer hours | needless holds | missed faults | lots at risk |
|---|---|---|---|---|
| Always hold (manual investigation) | 250 | 57 | 0 | 0 |
| Fixed playbook | 17 | 7 | 21 | 43 |
| **Agent** | **17** | **0** | **0** | **0** |

Assumptions, from `python -m fabtriage impact`: a manual investigation of a held alarm takes 2.5 engineer hours (a practicing fab data scientist told us false-alarm holds usually clear in 2 to 3 hours); reviewing a cited disposition takes about 10 minutes; a missed chamber fault runs about two more lots before the next sampled wafer catches it. These are estimates, not fab measurements.

### Limits

- The fab is simulated and small: one deposition step, four chambers, seven fault types. Real fabs have more tools, more steps and faults no list anticipates.
- Fourteen cases per held-out set is small; one wrong case moves accuracy by 7 points.
- The scenarios follow public sources and practitioner input ([docs/SCENARIOS.md](docs/SCENARIOS.md)), but the simulator is not calibrated to production data.

## Run it

See it without an API key:

```bash
pip install -r requirements.txt
python -m fabtriage demo      # opens the read-only demo in your browser
```

Everything else:

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

## Demo site

`python -m fabtriage export --out docs/demo` writes the console as a static, read-only site from the saved runs; GitHub Pages serves it from `docs/`. It has the alarm queue, every investigation with a step-by-step replay, the side-by-side comparison and the benchmark. Live investigations, sign-off and voice notes need an API key, so they run in the local version:

```bash
cp .env.example .env    # add your MODEL_API_KEY
python -m fabtriage serve
```

## Console

```bash
python -m fabtriage serve     # http://127.0.0.1:8770
```

The first screen is the alarm queue: what needs an engineer, then proposed holds, then proposed releases. Open an alarm to see the verdict card (decision, cause, the evidence behind it, sign-off) and, below it, the investigation step by step: each tool call with its evidence id, the agent's reasoning, verifier refusals, the final disposition with every claim linked back to its evidence, the chamber's SPC chart and the SAM-segmented wafer maps. An engineer approves the disposition, or rejects it with a note and the agent investigates again with that note. The note can be spoken: the console records it and Muse Voice Transcribe turns it into text, because typing in cleanroom gloves is slow. The Benchmark tab compares the agent with the baselines.

## Scope note

This is a simplified, simulated fab. Process numbers are illustrative, not from any real fab. The scenarios follow failure modes that practicing fab data scientists described, but the simulator is not calibrated to production data.
