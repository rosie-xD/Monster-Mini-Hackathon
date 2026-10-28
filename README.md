# Mini Monster Hack — pick your file

**Three standalone Python scripts. One per teammate. No packages to install.**
Use Python 3.10 or newer (`python3 --version`). You can download just your script
and run it next to your data, or clone this repository's `monster-detector` branch.

| File | What it finds |
| --- | --- |
| [ghost.py](ghost.py) | Active in ≥3 of the first 4 Autumn weeks, then a weekly activity average below 10% of the early average |
| [zombie.py](zombie.py) | Activity lasting more than 3 hours, with no gap longer than 15 minutes |
| [vampire.py](vampire.py) | More than 21 nighttime-active dates, and more nighttime dates than daytime dates |

## Run your file

Open Terminal in the folder containing your script. Replace the quoted filenames
with your own files. Both LMS and video activity are required.

```bash
python3 ghost.py --lms "lms.csv" --video "video.csv.zip" --calendar "calendar.csv"
```

```bash
python3 zombie.py --lms "lms.csv" --video "video.csv.zip"
```

```bash
python3 vampire.py --lms "lms.csv" --video "video.csv.zip"
```

CSV and ZIP files work directly. Headers must include `P_ID` and `TIMESTAMP`.
Ghost also needs `DATE` and the real calendar (`DATE`, `WEEK_NUMBER`, `ACADEMIC_YEAR`).
Column order doesn't matter. For the split LMS CSV from your Desktop:

```bash
python3 zombie.py --lms-parts "$HOME/Desktop/"lms_part_* --video "video.csv.zip"
```

Include **all parts** from one split of the uncompressed CSV. Do not add headers to
individual byte parts. Use `python3 zombie.py --help` for additional options.

## Get your results

The script prints its new results folder, such as `results/zombie/<run-id>/`.
Open **findings.csv** for matching student IDs and **student_evidence.csv** for the
supporting counts. Zombie also writes **zombie_sequences.csv** with qualifying
start/end times, duration and largest gap. **run_summary.json** confirms completion.
A new folder is used each time. Input files are not changed.

Each script streams data to a temporary disk database; it does not load all 7 million
rows into memory. Leave several GB of disk space free. Running all three scripts
separately reads the data three times. Use complete histories; add `--sample` when
working on an incomplete extract, and treat those results as provisional.

## Assumptions to know

- **Ghost:** count activity rows, not `INTERACTION_COUNT`. Use all 52 calendar weeks,
  including weeks with zero activity. Exactly 10% does not qualify.
- **Zombie:** use observed start timestamps, not summed viewing/interaction durations.
  Exactly 3 hours fails; exactly 15-minute gaps pass. Both activity sources are combined.
- **Vampire:** count distinct dates. Night is `(00:00,05:00]`; exactly midnight belongs
  to the previous daytime date. A date may count as both day and night. Default is UTC;
  use `--timezone Europe/London` if the organisers intend UK local time. These boundary
  and timezone interpretations are preserved from the previous version, not a confirmed
  organiser ruling.
- Duplicate activity rows are retained. Missing rows can distort all three results.
  Missing/invalid required fields fail with an error rather than being silently skipped.

## Try it without real data

The optional [synthetic examples](examples/synthetic) contain invented students:

```bash
python3 ghost.py --lms examples/synthetic/lms.csv --video examples/synthetic/video.csv --calendar examples/synthetic/calendar.csv
python3 zombie.py --lms examples/synthetic/lms.csv --video examples/synthetic/video.csv
python3 vampire.py --lms examples/synthetic/lms.csv --video examples/synthetic/video.csv
```

Each finds one corresponding `SYNTH_*` student. Never use the synthetic calendar
as a replacement for the real event calendar.

## Teamwork and tests

Edit only your monster's file; its detection rule is the first section. Push changes
on a feature branch and open a PR into **monster-detector**. Keep student data and
results out of Git. The extra test/example folders are optional for running your file.

```bash
python3 -m unittest tests.test_scripts.GhostTests -v
python3 -m unittest tests.test_scripts.ZombieTests -v
python3 -m unittest tests.test_scripts.VampireTests -v
python3 -m unittest discover -s tests -v
```

The full suite tests each standalone script, CSV/ZIP/split input, threshold boundaries,
output protection and 100,002 synthetic rows. GitHub Actions runs it on Linux and macOS.
