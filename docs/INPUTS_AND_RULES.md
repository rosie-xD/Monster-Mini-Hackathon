# Detailed inputs, rules and outputs

A Python detector for the three behavioural monsters in the supplied Monster Guide.
It combines LMS and video activity, returns matching `P_ID`s, and saves the numbers
and sequences behind each result. **Python 3.10+; no third-party packages required.**

## Run on a Mac

Check `python3 --version`. If needed, install a current Python from
[python.org](https://www.python.org/downloads/). Open Terminal in this repository
and put your team copies of the data in a `data/` folder. Data and generated results
are excluded from Git. Replace the filenames below with yours:

```bash
python3 detect_monsters.py \
  --lms "data/la_mmh_training_lms_item_activity_by_session_fact.csv" \
  --video "data/la_mmh_training_video_activity_by_view_fact.csv.zip" \
  --calendar "data/la_mmh_calendar_dim.csv" \
  --output results/full
```

Inputs can be UTF-8 comma-separated CSVs or ZIPs containing one CSV each.
**Headers are required**; column order does not matter. Export XLSX as CSV first.
Both activity sources are required. The minimum columns are `P_ID`, `TIMESTAMP`,
and (when using the calendar) `DATE`. Other columns are not used.

If you used Mac `split -b 25m` on the **uncompressed LMS CSV**:

```bash
python3 detect_monsters.py \
  --lms-parts "$HOME/Desktop/"lms_part_* \
  --video "data/la_mmh_training_video_activity_by_view_fact.csv.zip" \
  --calendar "data/la_mmh_calendar_dim.csv" \
  --output results/full
```

Include **every part** from exactly one split operation. Parts are sorted by filename
and read as one byte stream, including rows/UTF-8 characters cut in half. Do not add
headers to byte parts. Missing parts cannot always be detected automatically.
This option is for split **CSV** bytes, not ZIP pieces. Separate complete CSVs, each
with headers, can instead be passed together to `--lms` or `--video`. Input files
must not overlap: supplying the same activity twice counts it twice.

Until you have the calendar, explicitly select only Zombie and Vampire:

```bash
python3 detect_monsters.py \
  --lms "data/lms.csv" --video "data/video.csv.zip" \
  --monsters Zombie Vampire --output results/zombie-vampire
```

By default each run uses `results/<selection>/<unique-run-id>/`. An explicit
`--output` directory must not already exist, even if empty; it is reserved atomically
so concurrent runs cannot overwrite each other.
Add `--sample` for incomplete extracts to mark outputs provisional. First-N-rows
samples do not preserve student histories: missing events break Zombie sequences,
can make students look like Ghosts, and distort Vampire counts. Full histories for
a selected set of students are more useful than random rows.

## Rules and assumptions

| Monster | Exact rule | Evidence |
| --- | --- | --- |
| Ghost | Active in ≥3 of weeks 1–4; `later_rows/48 < 0.10*(early_rows/4)` | Active early weeks, row counts, weekly averages and ratio |
| Zombie | Gaps between consecutive timestamps ≤15 minutes, with total sequence span >180 minutes | Start/end, duration, row count and largest gap |
| Vampire | Distinct nighttime dates >21 and > distinct daytime dates | Night/day date counts |

**Ghost:** count activity rows, not `INTERACTION_COUNT`. Include zero-activity weeks.
The dictionary defines academic week 1 as the first Autumn week and 52 weeks per
year. Use source `DATE` and the calendar's `WEEK_NUMBER`; do not guess term dates.
The calendar must cover the full selected year, all 52 weeks, without gaps or duplicate
dates. For multiple years specify `--academic-year 2023` using the exact calendar value.
Other calendar years are reported as excluded; activity dates absent from the calendar
fail validation. With a calendar, the selected year scopes all three detectors.
Without one, Zombie/Vampire use all supplied rows.

**Zombie:** measure continuity of observed activity **start timestamps**, across both
sources and midnight. Exactly 180 minutes does not qualify; a gap of exactly 15 minutes
is allowed. Microseconds are preserved. The dictionary describes video playback
duration and LMS time-before-next-interaction as **summed** values over sessions.
Those fields do not prove uninterrupted activity or reveal individual interaction
times, so they are not added to timestamps. Continuity inside one aggregated activity
row cannot be established by this detector.

**Vampire:** count dates, not rows/hours/minutes. Follow the guide's literal intervals:
night **(00:00, 05:00]**, day **(05:00, 24:00]**. Exact midnight counts against the
previous daytime date; exactly 05:00 counts as night. A date containing both day and
night activity counts in both sets. This boundary interpretation is recorded in the
run summary for the team to check with organisers.

Timestamps ending in `Z` are UTC. Vampire defaults to **UTC** because the provided
examples use `Z` and the dictionary does not specify local time. If the intended rule
uses UK local time, add `--timezone Europe/London`. Zombie always measures elapsed
time; Ghost uses the source `DATE` key. Offset-free timestamps require an explicit
source timezone, e.g. `--naive-timezone UTC`. Ambiguous/nonexistent local daylight-saving
times are rejected; supply timestamps with offsets instead.

Duplicate activity rows are preserved, consistent with Ghost's row-count definition.
They do not increase a Zombie sequence's span or a Vampire's distinct-date counts.
Students can match multiple monsters. Person/module/resource lookup tables are not
needed for these three detectors.

## Outputs

- `findings.csv`: `Monster Type,P_ID`, one row per monster/student finding. Check the
  event's manual-combined template before pasting.
- `student_evidence.csv`: metrics for each student with included activity. Unselected
  detectors are `not run`; metrics for unselected detectors are blank.
- `zombie_sequences.csv`: qualifying sequences and evidence, timestamps in UTC.
- `run_summary.json`: completion status, input paths, counts, scope, rules, timezone,
  assumptions and sample status. **Written only on successful completion.**

Source files are never changed. Malformed rows or invalid required values fail with
a file/line error rather than being silently skipped. Do not use partial outputs from
a failed run. Students without activity cannot satisfy these rules and are omitted.
Input completeness cannot be determined automatically.

## Large files

Rows stream in batches of 50,000 into a temporary SQLite database, indexed by student
and timestamp, then processed one student at a time. The SQLite page cache is 64 MiB
(not a total process memory cap). Sorting uses disk. Leave several GB free for a
660 MB dataset; storage and runtime depend on the data and disk speed. Progress is
printed every 500,000 rows. The database is removed on normal exit, including handled
errors; a crash may leave a temporary `monster-*` directory inside the output folder.

## Tests

```bash
python3 -m unittest discover -s tests -t . -v
```

Synthetic tests cover thresholds, combined sources, shuffled rows, zero-activity
weeks, timezones, ZIPs, CSV byte parts and invalid inputs. No uploaded student data
is bundled or used by the tests. Passing tests verifies the documented rules, not
accuracy against the organisers' hidden labels.
