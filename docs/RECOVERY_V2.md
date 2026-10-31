# Recovery, second version: spend more monitor wafers when the film is noisy (written before running it)

The stress test found that the recovery agent used about 1.8 monitor wafers per recovery at
every noise level, so at level 3 a single noisy wafer carried as much weight as a clean one.
This version adds one rule to the recovery prompt and changes nothing else:

> Before you release on a rate estimate, make sure it rests on at least two monitor wafers
> that agree within 4 Å at the same recipe time. If they disagree by more, or your estimate
> rests on one wafer and moves the recipe more than 2%, run another monitor wafer first.

Method name `agent_v2`. The original `agent` is untouched, so both can be compared.

## Where it runs

1. The stress levels the rule came from (seeds 19 to 23, 25 recoveries per level). This is
   the set we looked at, so a good result here is expected and proves little on its own.
2. Fresh seeds 24 to 28 at every level (`stress2_L0` to `stress2_L3`), which nobody has
   looked at, with the original agent and the fixed rules run there too for comparison.

One run each.

## What counts, on the fresh seeds

1. At levels 2 and 3, `agent_v2` has fewer off-target lots per recovery than `agent`.
2. At levels 0 and 1 it is not worse by more than 0.3 off-target lots per recovery (the rule
   should not cost much where the film is clean).
3. No out-of-spec lots.
4. Monitor wafers per recovery rise with the level (that is the point of the rule); the
   extra chamber time is reported as its cost.

Results are added below after the run.

## Results (added after the run, Oct 31)

Fresh seeds 24 to 28, 25 recoveries per level, one run each. Off-target lots per recovery,
with bootstrap intervals over cases:

| Level | `agent` | `agent_v2` | v2 minus agent, paired 95% interval | Monitor wafers, agent → v2 | Two-monitor rule | Oracle |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | 0.08 (0.00 to 0.20) | 0.08 (0.00 to 0.20) | 0.00 | 1.68 → 2.04 | 2.84 | 0.36 |
| 1 | 0.56 (0.16 to 1.08) | 0.52 (0.12 to 1.04) | -0.04 (-0.24 to 0.12) | 1.48 → 2.12 | 3.72 | 0.68 |
| 2 | 1.92 (1.24 to 2.72) | 1.88 (1.28 to 2.64) | -0.04 (-0.24 to 0.16) | 1.80 → 2.12 | 4.56 | 1.92 |
| 3 | 2.64 (2.00 to 3.28) | 2.52 (1.84 to 3.20) | -0.12 (-0.36 to 0.08) | 1.68 → 2.36 | 4.96 | 2.56 |

Against the four points:

1. At levels 2 and 3 `agent_v2` has fewer off-target lots: 1.88 against 1.92 and 2.52
   against 2.64. Met on the letter, but the differences are one to three lots over 25
   recoveries and every interval spans zero. Not a real improvement.
2. At levels 0 and 1 it is not worse (0.00 and -0.04). Met.
3. One out-of-spec lot at level 3, in `rec_seasoning@L3-24`, for both versions, with the same
   recipe (-1.56%) after four monitor wafers. The oracle, which knows the true rate, has two
   out-of-spec lots on the same recovery and one more on `seasoning-26`; the two-monitor rule
   has one there too. At this noise (2.2 times the base wafer noise) a lot can leave spec on
   wafer noise alone, so this is the floor, not a recovery mistake. Not met as written, and
   nothing in the recovery could have met it.
4. Monitor wafers rose from about 1.7 to 2.0 to 2.4 per recovery and climbed a little with
   the level (2.04, 2.12, 2.12, 2.36). Met, weakly. The cost is about 0.2 hours of chamber
   time per recovery.

So the rule does what it says, the agent spends a second wafer more often, and it buys almost
nothing: at levels 2 and 3 the plain agent already sits on the oracle (1.92 against 1.92,
2.64 against 2.56). What is left at high noise is not the starting recipe. It is the
production controller fed by noisy, half-sampled metrology, and on `metrology_bias` the
offset tool; both versions lose 20 to 21 lots there at level 3 and the same 10 on `no_shift`.
Better recovery at this noise means changing the controller, not the starting recipe. The
agent may already set the EWMA weight (0.1 to 0.6), and it almost never does: at level 3 all
25 releases, in both versions, left it at the default 0.3, and across all 200 releases on
these seeds only 8 moved it. A smaller weight at high noise, or the metrology offset put into
the controller, is the next step; it needs a rule about when to use the setting, and a test
like this one on fresh seeds.

The original `agent` stays the default. `agent_v2` is kept as a method so the comparison can
be rerun.
