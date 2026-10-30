# The send-back loop, measured (written before running it)

In the console an engineer can reject a disposition with a note, and the agent investigates
again with that note in front of it. Until now that was a demo feature with no numbers. This
test puts numbers on it.

## Setup

- Cases: every alarm the agent got wrong at stress level 3 (its worst level), from the saved
  run. At that level it held equipment that was fine: 11 needless holds, 0 missed faults.
- Two conditions, each alarm investigated again from scratch:
  - `with_note`: the same one-paragraph engineer note for every case. It says the hold is
    not approved, that a chamber comparison alone is not decisive at this noise, and asks the
    agent to check the film directly (re-measure on the other tool, wafer map, or the
    chamber's lots around the alarm), to release if the film is fine, and if the film really is
    off, to find which step is responsible before holding equipment. It never names the true
    cause.
  - `no_note`: the same alarm run again with nothing attached, to measure plain run-to-run
    variation.
- Model: Muse Spark 1.3. One run per condition.

## What counts

1. More alarms are fixed with the note than without it. If the no-note rerun fixes as many,
   the note did nothing and we say so.
2. The note does not create missed faults. A note that says "release if the film is fine" must
   not push the agent into releasing a lot from a chamber that really is off. Any new missed
   fault is reported as a cost of the note.
3. We report what the agent did differently: re-measurements and tool calls per case.

Results are added below after the run.
