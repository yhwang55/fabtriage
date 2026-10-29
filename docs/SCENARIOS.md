# Scenarios

Seven alarm types, each with a hidden ground truth. About half of the cases also carry a planted distraction (a routine PM on the alarm chamber, the alarm wafer routed through the suspect metrology or clean tool).

The simulator is illustrative. Its numbers are not taken from any real fab. What we tried to get right is how each cause shows up in the data, using public sources and the views of two practicing fab data scientists (former SK hynix, data-side roles, not fab operations).

## pm shift

**What happens.** A chamber comes back from PM running thick.

**How it shows in the data.** Only that chamber's mean jumps, starting right at the PM. FDC may show a small hint.

**Correct response.** Hold the lot and the chamber.

**Practitioner view.** Chambers are conditioned and recalibrated after PM, so a shift that survives into production points at the chamber. Engineers check per-tool box plots and time series around the PM.

**Public sources.**

- [US Patent 12,530,022, Process chamber qualification for maintenance process endpoint detection](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/12530022): A chamber is not ready for production right after maintenance and has to be brought back and qualified.
- [US Patent 6,512,991, Reducing deposition variation by modeling post-clean chamber performance](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/6512991): Deposition rate is lower for the first 10 to 25 wafers after a chamber clean.

## buildup drift

**What happens.** A chamber overdue for PM drifts up as material builds up inside it.

**How it shows in the data.** One chamber sits high for a long time with many wafers since PM; wafer maps are thick at the edge.

**Correct response.** Hold the lot and the chamber.

**Practitioner view.** Deposition shows buildup more clearly than etch: material collects inside the chamber and the rate usually rises with it. Fabs compensate by wafer count since PM, which hides most but not all of the drift.

**Public sources.**

- [US Patent 6,512,991, Reducing deposition variation by modeling post-clean chamber performance](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/6512991): Material builds up on the chamber's inner surfaces with use and changes the deposition rate.

## metrology error

**What happens.** MET02 misreads; the film is fine.

**How it shows in the data.** The reading is off but a re-measurement on MET01 is in spec. Sometimes every recent MET02 reading is high.

**Correct response.** Re-measure, then release.

**Practitioner view.** A metrology problem is suspected when values look implausible; a re-measurement on another tool settles it.

**Public sources.**

- [US Patent 7,532,999, Determining root cause of matching problem for a measurement system fleet](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/7532999): Tools in a metrology fleet are matched by measuring the same wafers and minimizing their offsets.
- [Metrology tool performance guaranteed, Solid State Technology, Feb 1999](https://sst.semiconductor-digest.com/issue/?id=18946): Thin-film thickness tools are matched to fractions of an angstrom and checked on reference wafers to catch drift.

## upstream clean

**What happens.** CLN02 leaves the surface in a state that deposits thick, on every chamber.

**How it shows in the data.** Only lots cleaned on CLN02 are high, on several chambers; wafer maps are thick in the center.

**Correct response.** Hold the lot, escalate to CLN02.

**Practitioner view.** Equipment or upstream problems are suspected when abnormal lots cluster in one group. One contact called upstream and shared-facility effects very frequent; the other thought them rare. We keep the scenario and note the disagreement.

**Public sources.**

- [US Patent 8,718,809, Comprehensive analysis of queue times in microelectronic manufacturing](https://patents.google.com/patent/US8718809): Film growth can be influenced by the pre-clean to deposition queue time.
- [Chien, Wang, Cheng (2007), Data mining for yield enhancement in semiconductor manufacturing, Expert Systems with Applications 33(1)](https://doi.org/10.1016/j.eswa.2006.04.014): Statistical tests over process history point to the tools behind an excursion, the idea behind commonality analysis.

## wafer noise

**What happens.** One wafer comes out a little thick for no lasting reason.

**How it shows in the data.** A single point outside control limits but inside spec; the chamber's history is normal.

**Correct response.** Release.

**Practitioner view.** False-alarm holds are usually cleared in two to three hours, at most half a day.

**Public sources.**

- [NIST/SEMATECH e-Handbook of Statistical Methods, section 6.3.2 (control charts)](https://itl.nist.gov/div898/handbook/pmc/section3/pmc32.htm): About 0.3% of points fall outside 3-sigma limits even when nothing is wrong, so single points raise false alarms.

## sensor fault

**What happens.** The heater temperature sensor reports a jump that never happened.

**How it shows in the data.** FDC alarm, but wafers processed after the jump have normal thickness.

**Correct response.** Flag the sensor, release.

**Practitioner view.** Each tool has its own sensor set, logged at about 10 Hz; sensor readings and film results can disagree.

**Public sources.**

- [Goodlin, Boning, Sawin, Wise, Simultaneous fault detection and classification for semiconductor manufacturing tools, 201st ECS Meeting (2002)](https://www.electrochem.org/dl/ma/201/pdfs/0413.pdf): Discusses FDC false alarms across many charts and faults that look like a biased sensor.

## heater drift

**What happens.** The heater really runs hot.

**How it shows in the data.** FDC alarm, and wafers processed after the jump are thick. The alarm lot itself was not measured.

**Correct response.** Hold the lot and the chamber.

**Practitioner view.** A real temperature change shows up in the film on wafers processed after it; a sensor fault does not.

**Public sources.**

- [Plummer, Deal, Griffin, course notes for Silicon VLSI Technology, ch. 9 (thin film deposition)](https://dunham.ece.uw.edu/ee528/notes/Chapter9.pdf): In the reaction-limited regime CVD deposition rate follows an Arrhenius law and is very temperature sensitive.
