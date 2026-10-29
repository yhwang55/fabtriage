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
