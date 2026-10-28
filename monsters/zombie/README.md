# Zombie teammate guide

Work in [detector.py](detector.py) and [tests/zombie](../../tests/zombie).

## Rule

Combine LMS and video timestamps for each student, sort by time, and split sequences
where a gap is **greater than 15 minutes**. Flag sequences lasting **more than 180
minutes** from first to last start timestamp. A 15-minute gap passes; exactly three
hours fails. Sequences can cross midnight and mix both sources. Duplicate timestamps
do not extend the span. Microseconds are preserved.

The dictionary's duration fields are sums over sessions, not evidence of uninterrupted
activity. The detector does not add playback duration or LMS aggregate duration to
timestamps. Continuous activity inside one aggregated row cannot be established.

## Run and test from the repository root

```bash
python3 -m monsters.zombie --lms examples/synthetic/lms.csv --video examples/synthetic/video.csv
python3 -m unittest discover -s tests/zombie -t . -v
```

For your team data:

```bash
python3 -m monsters.zombie --lms "data/lms.csv" --video "data/video.csv.zip"
```

Required activity headers: `P_ID`, `TIMESTAMP`. A calendar is optional; if provided,
`DATE` is also required and the selected academic year scopes the input. CSV, ZIP and
split CSV bytes are supported; see [input instructions](../../docs/INPUTS_AND_RULES.md).

## Evidence and limitations

Results go to `results/zombie/<unique-run-id>/`. `findings.csv` lists each matching
student once. `zombie_sequences.csv` gives each qualifying sequence's start/end in
UTC, duration, activity-row count and maximum gap. `student_evidence.csv` gives the
longest sequence and number of qualifying sequences per student. Other detectors
are `not run`; `run_summary.json` records inputs and scope.

Missing activity rows can break sequences and cause false negatives. Use complete
LMS and video histories for the same students. Timezone offsets are used to compute
elapsed time, so daylight-saving clock changes do not create extra elapsed hours.

## Module interface

Create a fresh `ZombieDetector` per student; call `add(instant, week, source)` in
timestamp order, then `finish()` once. `instant` is UTC integer microseconds. The
other fields provide a common interface but are not needed by the rule. The result
contains `matched`, `evidence` and qualifying `sequences`. No file I/O occurs here.
Keep the schema stable or coordinate changes through [CONTRIBUTING](../../CONTRIBUTING.md).
