# Vampire teammate guide

Work in [detector.py](detector.py) and [tests/vampire](../../tests/vampire).

## Rule and boundary convention

Count **distinct dates** with nighttime activity and distinct dates with daytime
activity across LMS and video. Flag a student only when nighttime dates **>21**
and nighttime dates **>** daytime dates. A date with both types counts in both sets;
many events on one date still count as one date per category.

The existing implementation interprets the guide literally: night **(00:00,05:00]**,
day **(05:00,24:00]**. Exactly 05:00 is night. Exactly midnight is the previous
daytime date. This is a documented interpretation, not a confirmed organiser ruling;
do not change it silently while refactoring.

Default timezone is **UTC**, matching the supplied `Z` timestamps. The dictionary
does not specify whether the intended night rule uses UK local time. Use
`--timezone Europe/London` if the organisers confirm that interpretation. The run
summary records the timezone and boundary assumptions.

## Run and test from the repository root

```bash
python3 -m monsters.vampire --lms examples/synthetic/lms.csv --video examples/synthetic/video.csv
python3 -m unittest discover -s tests/vampire -t . -v
```

For your team data:

```bash
python3 -m monsters.vampire --lms "data/lms.csv" --video "data/video.csv.zip"
```

Required activity headers: `P_ID`, `TIMESTAMP`. Calendar is optional; supplying it
also requires `DATE` and scopes activity to the selected academic year. CSV, ZIP and
split CSV bytes are supported; see [input instructions](../../docs/INPUTS_AND_RULES.md).

## Evidence and limitations

Results go to `results/vampire/<unique-run-id>/`. `findings.csv` lists matching IDs.
`student_evidence.csv` contains `night_days` and `day_days`; other detectors are
`not run`. `run_summary.json` records inputs, timezone and assumptions. Samples
with incomplete date histories cannot establish reliable night/day counts.

## Module interface

Construct `VampireDetector(ZoneInfo("UTC"))`, call `add(instant, week, source)` for
each event, then `finish()` once. Timestamps are UTC integer microseconds; conversion
to local dates/hours happens inside this module. The result has `matched` and
`evidence`. Keep field names stable; coordinate changes using
[CONTRIBUTING](../../CONTRIBUTING.md).
