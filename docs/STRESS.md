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

## Results (added after the run, Oct 30)

Diagnosis, right decisions (35 alarms per level, one run):

| Level | Agent | Same model, no tools | Playbook | Agent minus playbook, paired 95% interval |
| --- | --- | --- | --- | --- |
| 0 | 97.1% | 97.1% | 88.6% | +8.6 (0.0 to 20.0) |
| 1 | 100% | 80.0% | 71.4% | +28.6 (14.3 to 42.9) |
| 2 | 94.3% | 62.9% | 68.6% | +25.7 (11.4 to 40.0) |
| 3 | 68.6% | 54.3% | 65.7% | +2.9 (-14.3 to 20.0) |

Recovery, off-target lots per recovery (25 per level, one run):

| Level | Agent | Two-monitor rule | Oracle | Agent minus rule, paired 95% interval |
| --- | --- | --- | --- | --- |
| 0 | 0.32 | 3.04 | 0.56 | -2.72 (-4.40 to -1.32) |
| 1 | 0.68 | 3.64 | 0.80 | -2.96 (-4.32 to -1.68) |
| 2 | 1.80 | 4.68 | 1.52 | -2.88 (-4.52 to -1.40) |
| 3 | 3.16 | 5.48 | 3.28 | -2.32 (-3.64 to -1.20) |

Against the two statements:

1. Diagnosis: the agent's rate is above the playbook's at every level, but the margin is
   clear only at levels 1 and 2. At level 3 the two are level (+2.9, interval spans zero),
   and at level 0 the interval touches zero. Partly met.
2. Recovery: below the two-monitor rule at every level, with every interval below zero. Met.

How the agent breaks at level 3, from the traces: it does not start missing faults (0 missed,
against the playbook's 4); it starts holding things that were fine. 11 of its 35 decisions
were needless holds, mostly blaming the chamber for a noisy one-off wafer (4), an upstream
clean problem (4), a metrology misread (2) or a sensor fault (1). With 15% of lots measured
and film noise of 3.6 Å, chamber-to-chamber differences stop being readable and the agent
falls back on the safe side. One case went to an engineer after three refused dispositions.

Spending: in diagnosis the agent did look harder as evidence thinned (9.3 tool calls and
0.57 re-measurements per alarm at level 0, 12.2 and 1.14 at level 3). In recovery it did not:
monitor wafers stayed at about 1.8 per recovery at every level, so a single noisy monitor
weighed as much at level 3 as at level 0. That expectation was not met, and it is the
obvious next improvement.

The oracle knows the true starting recipe but runs the same default controller, so it is a
reference, not a strict floor: at levels 0 and 3 the agent came out slightly below it. In
recovery the agent tracks the oracle closely at every level; most of its remaining lots come
from `metrology_bias` (8, 16, 22, 36 lots at levels 0 to 3), the production-feedback limit
described in RECOVERY.md.
