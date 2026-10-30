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
