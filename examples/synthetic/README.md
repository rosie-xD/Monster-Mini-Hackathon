# Synthetic examples — no real student records

These 154 activity rows describe nine invented students, deliberately shuffled
across LMS and video sources. The calendar covers 52 complete seven-day weeks
starting 2 October 2023. It is a **synthetic fixture**, not the real event calendar.

Run from the repository root:

```bash
python3 detect_monsters.py --lms examples/synthetic/lms.csv --video examples/synthetic/video.csv --calendar examples/synthetic/calendar.csv
```

Expected findings are also saved in [expected_findings.json](expected_findings.json):

| P_ID | Expected finding | Reason |
| --- | --- | --- |
| SYNTH_GHOST | Ghost | Activity in weeks 1, 2, 3; no later activity |
| SYNTH_GHOST_EXACT_10_PERCENT | None | Later average is exactly 10%, not below it |
| SYNTH_ZOMBIE | Zombie | 195-minute sequence with 15-minute gaps across both sources |
| SYNTH_ZOMBIE_EXACT_180 | None | Exactly 180 minutes fails the strict duration rule |
| SYNTH_ZOMBIE_GAP_BREAK | None | One gap exceeds 15 minutes by a microsecond |
| SYNTH_VAMPIRE | Vampire | 22 nighttime dates, zero daytime dates |
| SYNTH_VAMPIRE_ONLY_21 | None | Only 21 nighttime dates |
| SYNTH_VAMPIRE_DAY_TIE | None | 22 nighttime and 22 daytime dates tie |
| SYNTH_NORMAL | None | One daytime activity row |

Both individual commands and the combined command are tested against these expected
findings. Results are written outside this folder by default. Use your real calendar
and complete team data when you are ready to analyse; do not use this calendar as a
substitute for the event's calendar.
