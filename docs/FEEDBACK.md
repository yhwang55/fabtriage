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

## Results (added after the run, Oct 30)

| | With the note | Without |
| --- | --- | --- |
| Fixed | 3 of 11 | 0 of 11 |
| Still wrong | 8 | 11 |
| New missed faults | 1 (see below) | 0 |
| Re-measurements per case | 1.73 | 1.09 |
| Tool calls per case | 15.7 | 12.5 |

Rerun without a note, all 11 came back with the same wrong conclusion: at this noise level
the mistakes are not run-to-run luck, they are what the evidence looks like to the agent.

With the note, 3 were fixed. Both metrology misreads were: the note asks for a re-measurement
on the other tool, the agent did it, the re-measurement came back in spec, and it released.
One of the four one-off wafers was fixed the same way. The other three one-off wafers, the
four upstream clean cases and the sensor fault stayed wrong: with 15% of lots measured the
clean-tool difference does not show up in a commonality test, and the note cannot supply
evidence that is not there.

The "new missed fault": on `upstream_clean@L3-21` the note pushed the agent to call an
out-of-spec lot a one-off wafer and release it. The verifier refused (an out-of-spec lot
cannot be released without an in-spec re-measurement), the agent kept looking, and the run
hit the 20-turn limit with no disposition. The score counts that as a missed fault because no
hold was filed; in the console it goes to an engineer unresolved. So the note's one bad push
was stopped by the verifier, not by the agent.

Against the criteria: (1) met, 3 fixed against 0; (2) not strictly met, one case ended
unresolved after the note pushed toward a release that the verifier blocked; (3) the agent did
investigate harder with the note, 1.6 more tool calls and 0.6 more re-measurements per case.

What this says: a one-line send-back works when it names a check that settles the question
(re-measure on the other tool). It does not work when the evidence itself is too thin, and
on those cases it costs more investigation for the same answer.
