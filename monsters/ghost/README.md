# Ghost teammate guide

Work in [detector.py](detector.py) and [tests/ghost](../../tests/ghost). The shared
loader and the other monster modules are separate, so most Ghost changes stay here.

## Rule

Combine LMS and video **activity rows** per student. Require activity in at least
three of academic weeks 1–4, then `later_rows / 48 < 0.10 * (early_rows / 4)`.
Zero-activity weeks stay in the denominator. Exactly 10% fails. The calendar defines
week 1 as the first Autumn week. `INTERACTION_COUNT` is not the row count.

## Run and test from the repository root

Try the included synthetic example:

```bash
python3 -m monsters.ghost --lms examples/synthetic/lms.csv --video examples/synthetic/video.csv --calendar examples/synthetic/calendar.csv
python3 -m unittest discover -s tests/ghost -t . -v
```

For your team data:

```bash
python3 -m monsters.ghost --lms "data/lms.csv" --video "data/video.csv.zip" --calendar "data/calendar.csv"
```

Activity headers: `P_ID`, `TIMESTAMP`, `DATE`. Calendar headers: `DATE`,
`WEEK_NUMBER`, `ACADEMIC_YEAR`. A complete 52-week calendar is required. Use
`--academic-year 2023` if it contains multiple years. All common CSV/ZIP/parts
options work; see [input instructions](../../docs/INPUTS_AND_RULES.md).

## Evidence and limitations

Results go to a unique `results/ghost/<run-id>/` folder. `findings.csv` has one
`Ghost,P_ID` finding per match; `student_evidence.csv` contains early active weeks,
early/later row counts, weekly averages and the later/early ratio. Other detectors
are `not run`. `run_summary.json` records scope and assumptions.

Use complete activity histories, including the rest of the academic year. A sample
with missing later rows can falsely look like a Ghost. Duplicate input rows are
preserved. Missing or duplicate calendar dates are errors. Dates in other calendar
years are excluded and counted in the summary. No term dates are guessed.

## Module interface

`GhostDetector.add(instant, week, source)` consumes one event. `instant` is integer
UTC microseconds, `week` is the validated academic week, and `source` is `LMS` or
`video`. Call `finish()` once to get a `DetectionResult` with `matched` and
`evidence`. It performs no file I/O. Keep evidence keys stable or coordinate updates
with the shared output owner; see [CONTRIBUTING](../../CONTRIBUTING.md).
