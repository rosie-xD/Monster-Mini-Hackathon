# Mini Monster Hack — one file per monster

**Python 3.10+. No packages to install.** Each script runs by itself; download only
what your teammate needs. Use team copies of the data. No real student records or
uploaded documents are stored in this repository.

| Script | What it detects |
| --- | --- |
| [zombie.py](zombie.py) | Sequences >3 hours, with no timestamp gap >15 minutes |
| [phantom.py](phantom.py) | Duplicate recorded activity rows |
| [ghost.py](ghost.py) | Early engagement followed by a weekly average below 10% |
| [vampire.py](vampire.py) | >21 nighttime-active dates and more night than daytime dates |
| [undead_student.py](undead_student.py) | Activity after deregistration |
| [doppelganger.py](doppelganger.py) | Identical recorded histories; exports both/all matching students |
| [werewolf.py](werewolf.py) | **Provisional** repeated weekly spikes in Autumn AND Spring |
| [web_crawler.py](web_crawler.py) | >200 distinct resources within a rolling 12-hour window |
| [shape_shifter.py](shape_shifter.py) | Dated programme switches; **requires supplementary programme history** |

## Run your script

Open Terminal beside the script and replace the filenames below with your own:

```bash
python3 zombie.py --lms "lms.csv" --video "video.csv.zip"
python3 phantom.py --lms "lms.csv" --video "video.csv.zip"
python3 ghost.py --lms "lms.csv" --video "video.csv.zip" --calendar "calendar.csv"
python3 vampire.py --lms "lms.csv" --video "video.csv.zip"
python3 undead_student.py --lms "lms.csv" --video "video.csv.zip" --persons "persons.csv"
python3 doppelganger.py --lms "lms.csv" --video "video.csv.zip"
python3 werewolf.py --lms "lms.csv" --video "video.csv.zip" --calendar "calendar.csv"
python3 web_crawler.py --lms "lms.csv" --video "video.csv.zip"
python3 shape_shifter.py --programme-history "programme_history.csv" --calendar "calendar.csv"
```

The supplied dictionary/ERD contains **no programme history**. Shape-shifter expects
supplementary `P_ID,EFFECTIVE_DATE,PROGRAMME_ID` records describing successive
single-programme assignments. Module/department choices are not a substitute.

CSV or ZIP containing one CSV is supported. For the raw CSV parts made on your Mac:

```bash
python3 zombie.py --lms-parts "$HOME/Desktop/"lms_part_* --video "video.csv.zip"
```

All activity scripts accept `--lms-parts` and `--video-parts`. Include every part
from one split operation; do not add headers to byte parts. Shape-shifter accepts
`--history-parts` for a split supplementary history CSV. Full CSVs each need headers.
Use `python3 <script>.py --help` for options; see [RULES.md](RULES.md) for exact
columns, thresholds, interpretation limits and Werewolf tuning.

## Results

Each run prints a new `results/<monster>/<run-id>/` folder containing:

- **findings.csv** — monster type and matching P_ID, one row per student.
- **student_evidence.csv** — the supporting counts or comparisons.
- **run_summary.json** — completion, assumptions, input scope and counts.
- Additional evidence files where needed: sequences, duplicate rows, matching groups,
  spikes or programme changes. Shape-shifter also lists ambiguous records in exceptions.

Werewolf findings are **provisional candidates**, marked by an extra `Status` column
in findings, and in evidence and the summary. Vampire defaults to UTC with night `(00:00,05:00]`; use `--timezone
Europe/London` if organisers intend UK local time. Phantom defaults to all-column
row equality; optional excluded IDs change that definition. Read [RULES.md](RULES.md)
before submitting findings.

Inputs are never changed. Output directories cannot be reused. Use complete histories;
`--sample` marks incomplete results provisional. Each script streams to a temporary
SQLite database rather than loading millions of rows into memory. Leave several GB
free; full-row comparison/indexing can require much more disk than the input CSV.
Each standalone run reads the input separately. A 7-million-row benchmark has not
been run; batch and large-input checks use synthetic records.

## Try it and collaborate

[All-nine synthetic examples](examples/all_monsters/README.md) provide copy-paste
commands and known findings without real data. The existing [three-monster examples](examples/synthetic)
also remain available. To test everything:

```bash
python3 -m unittest discover -s tests -v
```

To test Zombie's rule alone: `python3 -m unittest tests.test_scripts.ZombieTests -v`.
Tests cover standalone execution, ZIP/byte parts, strict thresholds, false matches,
rolling-window checks and 100,000+ rows. GitHub Actions runs them on Linux/macOS.

Each teammate edits their monster's file. Use a feature branch and PR into
**monster-detector**, coordinate rule changes, and keep student data/results out of Git.
The original Zombie, Ghost and Vampire scripts retain their existing behaviour.
