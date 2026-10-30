# Large held-out evaluation (written before running it)

The earlier held-out sets were small: 14 alarms and 10 recoveries each. "14 out of 14" says
little about the next hundred alarms. This set is bigger and is analysed with confidence
intervals. Nobody has looked at its cases; nothing in the agent changes before it runs.

## The set

- Diagnosis: 70 alarms, seeds 9 to 18 of all seven scenarios (`--split holdout3`).
- Recovery: 50 recoveries, seeds 9 to 18 of all five scenarios.
- Agent (Muse Spark 1.3): 3 runs of each set. Fixed methods: 1 run (they are deterministic).
- Also once each: the same model without tools (`oneshot`) and the agent without the verifier
  (`agent_noverify`) on diagnosis.
- Separately, the clue-removal check on the fresh recovery set is repeated to 3 runs per
  condition (it was 1 run each).

## Analysis

Each case counts once. A method that ran several times gets its per-case mean over runs,
and the 95% interval comes from a bootstrap over cases (10,000 resamples), so repeats do not
pass for extra cases. Method comparisons are paired: both methods on the same resampled
cases. Code: `fabtriage/stats.py`, output: `python -m fabtriage report --split holdout3`.

## Criteria

Diagnosis:

1. The agent makes the right decision more often than the fixed playbook, and the 95%
   interval of the paired difference stays above zero.
2. The agent misses fewer real faults per run than the playbook.
3. The lower end of the agent's 95% interval for the right-decision rate is at least 85%.

Recovery:

4. The agent has fewer off-target lots per recovery than the two-monitor rule, and the 95%
   interval of the paired difference stays below zero.
5. No out-of-spec lots in any agent run.
6. At most 3 monitor wafers per recovery on average.

Every number is reported whether or not it meets these, with the cases the agent got wrong.

Fixed methods, already run when this was written: playbook 78.6% right decisions
[68.6, 87.1], 8 missed faults; always-hold 42.9%; two-monitor rule 1.86 off-target lots per
recovery [1.22, 2.58] and no out-of-spec lots.
