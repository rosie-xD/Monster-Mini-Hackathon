# All-nine-monster demo — invented records only

These files contain 247 LMS rows, 120 video rows, a synthetic calendar/person lookup,
and **supplementary invented** programme assignments. No uploaded student records are
included. The programme-history schema does not exist in the standard event dataset;
it is an explicit additional input for Shape-shifter.

Run from the repository root (Python 3.10+):

```bash
python3 zombie.py --lms examples/all_monsters/lms.csv --video examples/all_monsters/video.csv
python3 phantom.py --lms examples/all_monsters/lms.csv --video examples/all_monsters/video.csv
python3 ghost.py --lms examples/all_monsters/lms.csv --video examples/all_monsters/video.csv --calendar examples/all_monsters/calendar.csv
python3 vampire.py --lms examples/all_monsters/lms.csv --video examples/all_monsters/video.csv
python3 undead_student.py --lms examples/all_monsters/lms.csv --video examples/all_monsters/video.csv --persons examples/all_monsters/persons.csv
python3 doppelganger.py --lms examples/all_monsters/lms.csv --video examples/all_monsters/video.csv
python3 werewolf.py --lms examples/all_monsters/lms.csv --video examples/all_monsters/video.csv --calendar examples/all_monsters/calendar.csv
python3 web_crawler.py --lms examples/all_monsters/lms.csv --video examples/all_monsters/video.csv
python3 shape_shifter.py --programme-history examples/all_monsters/programme_history.csv --calendar examples/all_monsters/calendar.csv
```

Each command prints a separate output folder. Compare `findings.csv` to
[expected_findings.json](expected_findings.json):

| Script | Expected IDs |
| --- | --- |
| Zombie | SYNTH_ZOMBIE |
| Phantom | SYNTH_PHANTOM |
| Ghost | SYNTH_GHOST |
| Vampire | SYNTH_VAMPIRE |
| Undead Student | SYNTH_UNDEAD |
| Doppelgänger | SYNTH_TWIN_A and SYNTH_TWIN_B |
| Werewolf | SYNTH_WEREWOLF — **provisional heuristic candidate** |
| Web Crawler | SYNTH_CRAWLER |
| Shape-shifter | SYNTH_SHAPE — uses the supplied invented programme history |

The synthetic calendar starts on 2 October 2023 and has 52 seven-day weeks. Its
term labels are only a fixture; never substitute this file for the real calendar.
The same scripts are tested with negative and boundary cases in `tests/`.
