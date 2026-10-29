"""Where each scenario comes from: public sources plus what practicing fab data scientists told us.

Shown in the console next to the ground truth and listed in docs/SCENARIOS.md. Practitioner
notes are paraphrased and anonymous; both contacts worked on the data side (SK hynix,
Gauss Labs), not in fab operations.
"""

SOURCES = {
    "pm_shift": {
        "public": [
            ("US Patent 12,530,022, Process chamber qualification for maintenance process endpoint detection",
             "https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/12530022",
             "A chamber is not ready for production right after maintenance and has to be brought back and qualified."),
            ("US Patent 6,512,991, Reducing deposition variation by modeling post-clean chamber performance",
             "https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/6512991",
             "Deposition rate is lower for the first 10 to 25 wafers after a chamber clean."),
        ],
        "practitioner": "Chambers are conditioned and recalibrated after PM, so a shift that survives into production "
        "points at the chamber. Engineers check per-tool box plots and time series around the PM.",
    },
    "buildup_drift": {
        "public": [
            ("US Patent 6,512,991, Reducing deposition variation by modeling post-clean chamber performance",
             "https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/6512991",
             "Material builds up on the chamber's inner surfaces with use and changes the deposition rate."),
        ],
        "practitioner": "Deposition shows buildup more clearly than etch: material collects inside the chamber and the "
        "rate usually rises with it. Fabs compensate by wafer count since PM, which hides most but not all of the drift.",
    },
    "metrology_error": {
        "public": [
            ("US Patent 7,532,999, Determining root cause of matching problem for a measurement system fleet",
             "https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/7532999",
             "Tools in a metrology fleet are matched by measuring the same wafers and minimizing their offsets."),
            ("Metrology tool performance guaranteed, Solid State Technology, Feb 1999",
             "https://sst.semiconductor-digest.com/issue/?id=18946",
             "Thin-film thickness tools are matched to fractions of an angstrom and checked on reference wafers to catch drift."),
        ],
        "practitioner": "A metrology problem is suspected when values look implausible; a re-measurement on another tool settles it.",
    },
    "upstream_clean": {
        "public": [
            ("US Patent 8,718,809, Comprehensive analysis of queue times in microelectronic manufacturing",
             "https://patents.google.com/patent/US8718809",
             "Film growth can be influenced by the pre-clean to deposition queue time."),
            ("Chien, Wang, Cheng (2007), Data mining for yield enhancement in semiconductor manufacturing, "
             "Expert Systems with Applications 33(1)",
             "https://doi.org/10.1016/j.eswa.2006.04.014",
             "Statistical tests over process history point to the tools behind an excursion, the idea behind commonality analysis."),
        ],
        "practitioner": "Equipment or upstream problems are suspected when abnormal lots cluster in one group. One contact "
        "called upstream and shared-facility effects very frequent; the other thought them rare. We keep the scenario "
        "and note the disagreement.",
    },
    "wafer_noise": {
        "public": [
            ("NIST/SEMATECH e-Handbook of Statistical Methods, section 6.3.2 (control charts)",
             "https://itl.nist.gov/div898/handbook/pmc/section3/pmc32.htm",
             "About 0.3% of points fall outside 3-sigma limits even when nothing is wrong, so single points raise false alarms."),
        ],
        "practitioner": "False-alarm holds are usually cleared in two to three hours, at most half a day.",
    },
    "sensor_fault": {
        "public": [
            ("Goodlin, Boning, Sawin, Wise, Simultaneous fault detection and classification for semiconductor "
             "manufacturing tools, 201st ECS Meeting (2002)",
             "https://www.electrochem.org/dl/ma/201/pdfs/0413.pdf",
             "Discusses FDC false alarms across many charts and faults that look like a biased sensor."),
        ],
        "practitioner": "Each tool has its own sensor set, logged at about 10 Hz; sensor readings and film results can disagree.",
    },
    "heater_drift": {
        "public": [
            ("Plummer, Deal, Griffin, course notes for Silicon VLSI Technology, ch. 9 (thin film deposition)",
             "https://dunham.ece.uw.edu/ee528/notes/Chapter9.pdf",
             "In the reaction-limited regime CVD deposition rate follows an Arrhenius law and is very temperature sensitive."),
        ],
        "practitioner": "A real temperature change shows up in the film on wafers processed after it; a sensor fault does not.",
    },
}
