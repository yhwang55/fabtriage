# Stress test: where does it break? (written before running the agent)

On the large held-out set the agent made the right call on all 70 alarms. A score at the
ceiling says little about how much margin there is. This test makes the evidence weaker,
step by step, and watches where each method starts to fail.

## What changes

Faults keep their size, so every alarm is still a real alarm. What gets harder is the
evidence around it:

| Level | Lot-to-lot film noise | Lots with a measured wafer | Time since the fault began |
| --- | --- | --- | --- |
| 0 | 1.2 Å (as before) | 50% | as before |
| 1 | 2.0 Å | 35% | 60% of before |
| 2 | 2.8 Å | 25% | 40% of before |
| 3 | 3.6 Å | 15% | 25% of before |

Fewer measured lots and a more recent start mean fewer wafers that show the fault; more noise
means normal chambers wander closer to the limits. When the alarm lot happens to read inside
the limits at a higher level (so no alarm would fire), that history is redrawn.

Recovery at level k multiplies film and metrology noise by 1, 1.4, 1.8 and 2.2. A single
monitor wafer says less as noise grows. An `oracle` that reads the hidden truth and sets the
perfect recipe shows the off-target lots nobody could avoid at each level.

Fresh seeds 19 to 23 of every scenario: 35 alarms and 25 recoveries per level, the same seeds
at every level. Agent and the no-tools model: one run per level. Fixed methods: one run.

## What we expect, and what counts

This is a measurement, not a pass/fail test. We report every level, whatever happens. Two
statements we will check:

1. The agent's right-decision rate stays above the fixed playbook's at every level.
2. The agent's off-target lots per recovery stay below the two-monitor rule's at every level.

We also expect the agent to spend more (tool calls, re-measurements, monitor wafers) as
evidence weakens. If it does not, that is a finding too.

Fixed methods, already run when this was written:

| Level | Playbook, right decisions | Two-monitor rule, off-target lots per recovery | Oracle floor |
| --- | --- | --- | --- |
| 0 | 88.6% | 3.04 | 0.56 |
| 1 | 71.4% | 3.64 | 0.80 |
| 2 | 68.6% | 4.68 | 1.52 |
| 3 | 65.7% | 5.48 | 3.28 |

## Results (added after the runs, Oct 30; agent repeated three times)

The agent (Muse Spark 1.3) ran three times at every level, so each cell is the mean over
runs with a bootstrap interval over the 35 alarms or 25 recoveries. The open-weights model
(Muse Spark Open on Baseten), the no-tools model and the rules ran once.

Diagnosis, right decisions (35 alarms per level):

| Level | Agent (3 runs) | Open model | Same model, no tools | Playbook | Agent minus playbook, paired 95% interval |
| --- | --- | --- | --- | --- | --- |
| 0 | 98.1% (94.3 to 100) | 94.3% | 97.1% | 88.6% | +9.5 (1.0 to 20.0) |
| 1 | 97.1% (92.4 to 100) | 97.1% | 80.0% | 71.4% | +25.7 (12.4 to 41.0) |
| 2 | 96.2% (89.5 to 100) | 85.7% | 62.9% | 68.6% | +27.6 (14.3 to 42.9) |
| 3 | 68.6% (53.3 to 82.9) | 62.9% | 54.3% | 65.7% | +2.9 (-13.3 to 19.0) |

Per run the agent scored 97.1, 97.1, 100 at level 0; 100, 97.1, 94.3 at level 1; 94.3,
97.1, 97.1 at level 2; and 68.6 in all three runs at level 3. Missed real faults per run:
none at levels 0 and 1, one in one run at level 2, one in one run at level 3 (the playbook
missed 2, 5, 7 and 4).

Recovery, off-target lots per recovery (25 per level):

| Level | Agent (3 runs) | Open model | Two-monitor rule | Oracle | Agent minus rule, paired 95% interval |
| --- | --- | --- | --- | --- | --- |
| 0 | 0.29 (0.01 to 0.75) | 0.36 | 3.04 | 0.56 | -2.75 (-4.43 to -1.35) |
| 1 | 0.68 (0.17 to 1.28) | 0.84 | 3.64 | 0.80 | -2.96 (-4.35 to -1.68) |
| 2 | 1.80 (1.15 to 2.49) | 1.72 | 4.68 | 1.52 | -2.88 (-4.52 to -1.43) |
| 3 | 3.25 (2.33 to 4.31) | 3.56 | 5.48 | 3.28 | -2.23 (-3.53 to -1.11) |

No agent run at any level produced an out-of-spec lot; the two-monitor rule produced 1 at
level 2 and 2 at level 3.

Against the two statements:

1. Diagnosis: the agent's rate is above the playbook's at every level, and with three runs
   the margin is clear at levels 0, 1 and 2 (every interval above zero). At level 3 the two
   are level (+2.9, interval spans zero). Mostly met; the break point is level 3.
2. Recovery: below the two-monitor rule at every level, with every interval below zero. Met.

How the agent breaks at level 3, from the traces: it does not start missing faults (0, 0 and
1 missed over three runs, against the playbook's 4); it starts holding things that were fine.
10 or 11 of its 35 decisions in every run were needless holds, and mostly the same alarms:
9 failed in all three runs, 13 failed in at least one. The holds blame the chamber for a noisy one-off wafer (4), an upstream clean
problem (4), a metrology misread (2) or a sensor fault (1). With 15% of lots measured and
film noise of 3.6 Å, chamber-to-chamber differences stop being readable and the agent falls
back on the safe side. A rerun of those 11 alarms with no change gave the same 11 wrong
answers, so this is what the evidence looks like to the model, not run-to-run luck
([FEEDBACK.md](FEEDBACK.md) measures what a one-line engineer note does about it: 3 of 11
fixed).

Spending: in diagnosis the agent did look harder as evidence thinned (9.3 tool calls and
0.57 re-measurements per alarm at level 0, 12.2 and 1.14 at level 3). In recovery it did not:
monitor wafers stayed at 1.6 to 1.8 per recovery at every level, so a single noisy monitor
weighed as much at level 3 as at level 0. That expectation was not met. A second version of
the recovery prompt that asks for a second agreeing monitor wafer before releasing was tested
on fresh seeds in [RECOVERY_V2.md](RECOVERY_V2.md); it spent the wafers and changed the result
by one to three lots over 25 recoveries, because at these levels the agent is already on the
oracle.

The open model tracks the agent within a few points at levels 0 and 1 and falls further
behind at levels 2 and 3 (10.5 and 5.7 points, both intervals above zero). It breaks the same
way, holding the chamber for upstream and one-off-wafer alarms, and in about a third of its
failures it runs out of turns without filing anything. In recovery it is within 0.3 lots per recovery of Muse Spark 1.3 at every
level and uses more monitor wafers (2.5 to 3.0 against 1.6 to 1.8).

The oracle knows the true starting recipe but runs the same default controller, so it is a
reference, not a strict floor: at levels 0, 1 and 3 the agent came out at or slightly below
it. Most of the agent's remaining lots come from `metrology_bias`, the production-feedback
limit described in RECOVERY.md.
