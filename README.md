# Mini Monster Hack — three teammates, three detectors

Find Ghost, Zombie and Vampire patterns in LMS + video activity, with evidence for
each matching student. **Python 3.10+ and its standard library only.** Start with the
included synthetic data; no real student records are stored in this repository.

| Teammate area | Code and instructions | Tests |
| --- | --- | --- |
| **Ghost** | [monsters/ghost](monsters/ghost) | [tests/ghost](tests/ghost) |
| **Zombie** | [monsters/zombie](monsters/zombie) | [tests/zombie](tests/zombie) |
| **Vampire** | [monsters/vampire](monsters/vampire) | [tests/vampire](tests/vampire) |

See [CONTRIBUTING.md](CONTRIBUTING.md) for feature branches, pull requests and shared
code coordination. Integration happens on **`monster-detector`**, not automatically
on `main`.

## Get started on macOS

Install Python 3.10 or newer from [python.org](https://www.python.org/downloads/)
if `python3 --version` is missing or too old. No `pip install` step is needed.

For a new checkout:

```bash
git clone --branch monster-detector https://github.com/rosie-xD/Monster-Mini-Hackathon.git
cd Monster-Mini-Hackathon
python3 --version
```

If you already cloned it, use that checkout, preserve any local changes, and run:

```bash
git fetch origin
git switch monster-detector
git pull --ff-only origin monster-detector
```

Run every command below **from the repository root**.

## Try your own monster

These commands use only the small committed synthetic fixtures. Each detector has
its own entry point and can be tested independently.

**Ghost**

```bash
python3 -m monsters.ghost --lms examples/synthetic/lms.csv --video examples/synthetic/video.csv --calendar examples/synthetic/calendar.csv
python3 -m unittest discover -s tests/ghost -t . -v
```

**Zombie**

```bash
python3 -m monsters.zombie --lms examples/synthetic/lms.csv --video examples/synthetic/video.csv
python3 -m unittest discover -s tests/zombie -t . -v
```

**Vampire**

```bash
python3 -m monsters.vampire --lms examples/synthetic/lms.csv --video examples/synthetic/video.csv
python3 -m unittest discover -s tests/vampire -t . -v
```

Each example finds one corresponding `SYNTH_*` student. See the
[example explanation and expected findings](examples/synthetic/README.md).

## Run all three and test everything

```bash
python3 detect_monsters.py --lms examples/synthetic/lms.csv --video examples/synthetic/video.csv --calendar examples/synthetic/calendar.csv
python3 -m unittest discover -s tests -t . -v
```

The combined command loads each input once, creates one disk index, and sends a
single sorted stream to the selected detectors. To select a subset with the original
CLI, add `--monsters Zombie Vampire`. Unselected detectors do not run.

GitHub Actions runs the tests on pushes and pull requests, using Python 3.10 and
3.13 on Linux and macOS. The tests cover rule boundaries, individual/combined parity,
ZIPs, split CSVs, malformed inputs, output isolation and a 100,002-row synthetic case.
They do not establish accuracy against hidden event labels or benchmark 7 million rows.

## Use your team copies when ready

Place actual files in the ignored `data/` folder and replace the example paths:

```bash
python3 detect_monsters.py \
  --lms "data/lms.csv" \
  --video "data/video.csv.zip" \
  --calendar "data/calendar.csv"
```

Or use just your module, e.g. `python3 -m monsters.zombie --lms "data/lms.csv"
--video "data/video.csv.zip"` as one line. CSVs, single-CSV ZIPs and raw CSV byte
parts are supported. For the LMS parts made by the Mac `split` command:

```bash
python3 -m monsters.zombie --lms-parts "$HOME/Desktop/"lms_part_* --video "data/video.csv.zip"
```

All parts must come from the same uncompressed CSV and be present. The original
header is required once across the byte stream. For multiple complete CSV files,
each must have headers and should be passed to `--lms` or `--video` instead.

Ghost requires the **real complete calendar**, including academic weeks 1–52. Zombie
and Vampire do not require a calendar, but supplying one scopes them to the selected
academic year too. For multiple calendar years add `--academic-year 2023`. For
incomplete extracts add `--sample`; missing histories can invalidate conclusions.

See [detailed inputs, rules and outputs](docs/INPUTS_AND_RULES.md) for validation,
CSV formats, large-file storage requirements and interpretation limits.

## Results and rules

Every run prints a unique output folder:

```text
results/ghost/<run-id>/
results/zombie/<run-id>/
results/vampire/<run-id>/
results/all/<run-id>/
```

Use `--output results/your-new-folder` if desired. The specified directory must not
already exist, even if empty. Each run reserves its folder atomically, so teammates
and simultaneous runs cannot overwrite one another's files.

- **findings.csv**: `Monster Type,P_ID`, one finding per student/monster pair.
- **student_evidence.csv**: row counts and detector metrics. Unselected flags are
  `not run` and their metrics are blank; IDs and columns are consistent across runs.
- **zombie_sequences.csv**: matching start/end sequences in UTC (header-only when
  Zombie is not selected).
- **run_summary.json**: completion, scope, timezone, inputs, assumptions and totals.
  Only a successful run writes this file; disregard partial files from failed runs.

| Monster | Rule |
| --- | --- |
| Ghost | Active in ≥3 of the first 4 Autumn weeks; later rows/48 < 10% of early rows/4, including zero-activity weeks |
| Zombie | Combined timestamp sequence >3 hours, with all consecutive gaps ≤15 minutes |
| Vampire | >21 distinct nighttime dates and more nighttime dates than daytime dates |

Vampire preserves the existing **UTC** default and intervals: night `(00:00,05:00]`,
day `(05:00,24:00]`; midnight is assigned to the previous daytime date. These timezone
and boundary interpretations need organiser confirmation; use `--timezone
Europe/London` if UK local time is intended. Zombie uses observed start timestamps,
not aggregate playback or interaction-duration totals. No rule interpretation has
been silently changed in this refactor.

## Repository map

```text
monsters/{ghost,zombie,vampire}/  Independent detector, CLI entry point, README
shared/                         Loading, calendar, time handling, pipeline, outputs, CLI
tests/{ghost,zombie,vampire}/    Independent rule tests
tests/integration/              Original regression tests and pipeline/CLI tests
examples/synthetic/             Small invented CSVs and expected findings
docs/INPUTS_AND_RULES.md         Detailed input and interpretation notes
CONTRIBUTING.md                 Team workflow and shared interfaces
.github/workflows/tests.yml     Automated tests on pushes and pull requests
detect_monsters.py              Backward-compatible combined entry point
```

Keep actual student data, uploaded documents and results out of Git. Only the
explicitly generated synthetic fixture CSVs are exempted from the data ignore rules.
