# Recovery after PM: bringing a held chamber back to target

FabTriage's first job ends with "hold the chamber". This second job starts there. The idea
comes from Prof. Jang (장재연, The Catholic University of Korea): run-to-run (R2R) models
need many runs and lose their footing after preventive maintenance, so engineers fall back on
guide rules and experience to re-center the recipe. Can an agent do that part?

Written before any agent run. Success criteria below are fixed in advance.

## The setting

- Film thickness = deposition rate × deposition time + wafer noise. Target 500 Å, control
  limits ±7 Å, spec ±15 Å.
- Before PM, wall buildup slowly lowered the rate and the EWMA controller stretched the time
  to compensate. PM resets the chamber, so the old recipe usually comes out thick.
- The controller after release is an EWMA on the deposition rate (λ 0.3 by default), updated
  from the roughly half of lots that get a measured wafer.
- Recovery starts with the chamber on hold. Whoever recovers it sets the recipe time and the
  controller settings and releases it. Then 40 production lots run, and we score them on the
  true film, not on what metrology reported.

## Scenarios (hidden from the agent)

| Scenario | What is going on | What a careless recovery does |
| --- | --- | --- |
| `post_pm_reset` | Buildup reset, rate jumps back up | Keeping the pre-PM recipe runs thick |
| `seasoning` | Seasoning wafers were skipped; the first two wafers after PM come out thin | Correcting from the first monitor wafers overshoots thick |
| `fast_drift` | A new showerhead was installed; film thins fast for the first lots | Plain EWMA lags behind and drifts out of control |
| `metrology_bias` | MET02 reads a few Å high (tool matching is off) | Correcting from MET02 alone runs thin |
| `no_shift` | PM changed nothing that matters | Over-correcting from noise makes things worse |

The PM record, the chamber's history from the previous PM cycle and the latest metrology
tool-matching check are all available. Whether they matter is for the recoverer to work out.

## Methods compared

- `keep_recipe`: release with the pre-PM recipe and let EWMA catch up. The data-hungry
  status quo.
- `reset_recipe`: guide rule. Go back to the baseline recipe time after PM, then EWMA.
- `monitor_rule`: guide rule. Run two monitor wafers on the default metrology tool, re-center
  the time on their mean, then EWMA.
- `agent`: Muse Spark with tools to read the PM record, the chamber history and the
  metrology matching check, run up to four monitor wafers, compute a recipe from a rate, and
  release with cited evidence. The same kind of verifier checks every release.

## Metrics

Per recovery, over the 40 production lots after release:

- Off-target lots: true lot mean outside the control limits (493 to 507 Å). Primary.
- Out-of-spec lots: outside 485 to 515 Å.
- Monitor wafers used, and the chamber downtime they cost (0.5 h each).
- Recipe change on `no_shift` cases.

## Success criteria (fixed before running the agent)

On the held-out recoveries (seeds 5 and 6, run once, agent repeated 3 times):

1. The agent has at least 30% fewer off-target lots than `keep_recipe`.
2. The agent has no more off-target lots than the best guide rule.
3. The agent causes no out-of-spec lots.
4. The agent uses at most 3 monitor wafers per recovery on average.
5. On `no_shift` cases the agent changes the recipe time by at most 1%.

If a criterion fails, the README says so and shows which scenarios the agent lost.

## What happened (added after the runs)

Development (20 recoveries, one run): 3 off-target lots for the agent against 45 for the
two-monitor rule and 87 for keeping the recipe. All 3 came from `metrology_bias`, after the
agent had correctly measured its monitor wafers on MET01: once in production, half the
measured lots still come from the offset MET02 and pull the EWMA controller thin. No method
here can fix that from the recipe; it needs the metrology tool fixed or the offset put into the
controller. Nothing was changed after the development run.

Held-out (10 recoveries, three runs): all five criteria met. Off-target lots 6, 6 and 30
(mean 14 ± 13.9) against 20 for the best guide rule; no out-of-spec lots; 1.67 monitor
wafers per recovery; no recipe change when nothing changed.

The one bad run: in `fast_drift-5`, repeat 3, the agent copied the history's thickness slope
(-0.82 Å per lot) into `drift_A_per_lot`, which expects thinning as a positive number. The
controller then pushed the film the wrong way and 24 of 40 lots went off target. The other two
repeats used +0.82 and had none. The verifier accepted it because it only checked that the
number came from evidence.

The fix is one verifier rule: a negative `drift_A_per_lot` is refused with a message that
says which sign to use. The tool description now says the same. Because this fix came from
reading a held-out failure, the fixed version is checked on a fresh held-out set (seeds 7
and 8) that nobody has looked at.

Fresh held-out (seeds 7 and 8, 10 recoveries, three runs, fixed version): all five criteria
met. Off-target lots 2, 2 and 2 against 21 for the two-monitor rule, 26 for the baseline
recipe and 39 for keeping the recipe; no out-of-spec lots; 1.67 monitor wafers per recovery
against the rule's 2; no recipe change when nothing changed. The 2 lots are the same
`metrology_bias` effect as in development. The agent used a positive drift in all six
`fast_drift` runs, so the new sign rule never had to fire; it is a guard, not the reason for
the result. The verifier sent back three releases over numbers it could not find in the cited
evidence (one was "40", read from the field name "first 40"); the agent fixed each on the
next try.

## Clue-removal check (written before running it)

The scenarios leave clues in the PM record (parts replaced, seasoning skipped, chamber not
opened) and in the chamber's earlier PMs (how fast film thinned after a showerhead swap, how
thin the first wafers came out without seasoning). A fair question: does the agent read the
evidence, or does it only work because the answer was planted where it looks?

So the agent runs the fresh held-out set (seeds 7 and 8) once more under three conditions:
earlier PMs hidden, PM details hidden, and both hidden. With PM details hidden the playbook
asks for at least one monitor wafer, since nobody knows what was done. Nothing else changes.

What we expect if the agent reads evidence rather than leaning on clues: with clues gone it
should spend more monitor wafers and still beat the two-monitor rule. Some scenarios can
still be read from monitor wafers alone (thin first wafers after skipped seasoning, a fast
thinning trend across several monitors); others cannot (the drift rate of a new part before
it shows). Criteria for each condition:

1. Off-target lots stay below the two-monitor rule on the same set (21).
2. No out-of-spec lots.
3. More monitor wafers than with all clues present (1.67 per recovery).

Whatever happens is reported per scenario.

### Result of the clue-removal check

All three criteria met in all three conditions (one run each, seeds 7 and 8):

| Condition | Off-target lots | Out-of-spec | Monitor wafers per recovery |
| --- | --- | --- | --- |
| All clues (3-run mean, from above) | 2 | 0 | 1.67 |
| Earlier PMs hidden | 9 | 0 | 2.1 |
| PM details hidden | 5 | 0 | 2.3 |
| Both hidden | 9 | 0 | 2.5 |
| Two-monitor rule (same set) | 21 | 0 | 2.0 |

Per scenario, reading the traces:

- `seasoning`: with both clue sources gone the agent ran four monitor wafers, saw the first
  two come out thin and the next two land high, and re-estimated from the last two only.
  0 off-target lots. With only the PM details hidden it once averaged all three monitors,
  thin ones included, and lost 1 lot.
- `fast_drift`: this is where the extra off-target lots come from (5 and 2). Without the
  earlier PMs the agent had no way to know a new showerhead thins fast, and it released with
  no drift pre-compensation. Its monitor wafers were run at different recipe times, which
  hides a per-run trend. This is the case we expected it to lose.
- `no_shift`: with the PM details hidden the agent could no longer tell the chamber was never
  opened, so it ran 2 or 3 monitor wafers to check, and kept the recipe within 0.18%.
- `metrology_bias`: unchanged; the matching check is not a hidden clue.

So the agent does lean on the clues where they carry information nothing else can give it
(how a new part will drift), and works the rest out from monitor wafers at some extra cost.

### Open model (Muse Spark Open on Baseten), fresh held-out set, one run

2 off-target lots, no out-of-spec lots, 2.5 monitor wafers per recovery (against 1.67 for
Muse Spark 1.3). Same decisions where it matters; it checks more before releasing.
