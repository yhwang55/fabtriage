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

## Results (added after the run, Oct 30)

All six criteria met.

1. Right decisions: agent 100% (70 of 70 in every run), playbook 78.6%. Paired difference
   21.4 points, 95% interval 12.9 to 31.4. Met.
2. Missed real faults per run: agent 0, playbook 8. Met.
3. Lower end of the agent's 95% interval: 94.8% (Wilson interval on 70 cases; the bootstrap
   has zero width when every case is right). Met.
4. Off-target lots per recovery: agent 0.23 (0.08 to 0.42), two-monitor rule 1.86. Paired
   difference -1.63, 95% interval -2.33 to -0.99. Met.
5. Out-of-spec lots in any agent run: 0. Met.
6. Monitor wafers per recovery: 1.66. Met.

Also measured: the same model without tools got 94.3% (88.6 to 98.6), 5.7 points below the
agent (1.4 to 11.4). Without the verifier the agent's decisions were all right too, but 19 of
70 dispositions did not cite the evidence the playbook requires (13 chamber holds without a
cited chamber comparison, 3 upstream escalations without a commonality test, 3 one-off-wafer
releases without the chamber's history); the verifier would have sent each back. The agent's 35
off-target recovery lots over three runs: 30 from `metrology_bias` (the production-feedback
limit described in RECOVERY.md) and 5 from `seasoning`.

The clue-removal check, repeated to three runs per condition, met its criteria in every
condition (see RECOVERY.md).

Open-weights model (Muse Spark Open on Baseten, one run on the same set): 94.3% right
decisions (88.6 to 98.6), 5.7 points below Muse Spark 1.3 (paired interval 1.4 to 11.4). Its
4 misses were all runs that hit the 20-turn limit without filing a disposition
(`metrology_error-14`, `upstream_clean-10`, `wafer_noise-14`, `wafer_noise-15`); one of them
was a real upstream fault, so it counts one missed fault. In recovery: 0.20 off-target lots
per recovery (0.04 to 0.40), no out-of-spec lots, 2.6 monitor wafers per recovery against
1.66.

Token use: about 3.7 million tokens per full diagnosis run (53 thousand per alarm) and 35
thousand per recovery. Wall time, median over all benchmark runs: 22 seconds per diagnosis
(27 on Baseten) and 31 seconds per recovery.
