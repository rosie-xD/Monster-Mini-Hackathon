# Rules, input contracts and interpretation limits

The uploaded Monster Guide is the rule source; the Student Guide and Main Briefing
explain HUNT/BUILD/TEST/PREDICT. The uploaded Data Dictionary and ERD define fields
and join keys. All were reviewed; no reference document was missing. The PowerPoint
briefing and its notes were also available. These documents are not committed here.
We do not analyse the real dataset as part of code development.

All scripts require Python 3.10+ and use only the standard library. Raw CSV values
remain text, preserving P_ID leading zeros. Required invalid fields stop the run
with a file/line error, rather than being silently skipped. File arguments accept
UTF-8 CSV or a ZIP containing one CSV. Byte parts must be complete and supplied from
one uncompressed CSV; missing parts cannot always be detected. Input files must not
overlap. A completed summary does not prove input completeness or official accuracy.

## Activity inputs and calendar

Both LMS and video are required by all activity scripts. Common columns are `P_ID`
and `TIMESTAMP`. `TIMESTAMP` must have a UTC offset (e.g. `Z`), or the caller must
explicitly set `--naive-timezone`. Ambiguous/nonexistent local daylight-saving times
without offsets are rejected. Duplicate input records are retained.

`DATE` is required whenever a calendar is supplied, and always for Undead Student.
Web Crawler and Doppelgänger require `LMS_ITEM_ID` in LMS and `VIDEO_ID` in video.
Phantom compares all supplied columns; genuine full source columns matter for
all-column equality. Header order is immaterial; original values and whitespace are
preserved by the six new scripts. The existing three scripts retain their original
whitespace trimming. IDs must be nonempty text, not null placeholders.

Ghost, Werewolf and Shape-shifter require a complete academic calendar with `DATE`,
`WEEK_NUMBER`, `ACADEMIC_YEAR`. Week 1 is the first Autumn week; there are 52 weeks
per the dictionary. Each week has seven days; week 52 may contain extra year-end days.
No gaps/duplicate dates are accepted. Select `--academic-year 2023` if multiple years
are present. Werewolf also requires date-to-`TERM` or date-to-`TERM_CODE` mapping;
module-level term codes do not establish calendar dates. The small committed calendar
is synthetic and must not replace the event's real calendar.

For scripts with optional calendars, a supplied calendar scopes **all** detection
to the selected year using the source DATE key. Unknown calendar dates fail; known
dates in other academic years are counted as excluded. Without a calendar, all
supplied activity is considered. No current date or institution term dates are guessed.

## Zombie — timestamp continuity

Sort LMS and video start timestamps together per P_ID. Split when a consecutive gap
is **>15 minutes**; qualify when last minus first timestamp is **>180 minutes**.
Exactly 15-minute gaps pass, exactly 3 hours fails. Microseconds and elapsed time
across timezone/DST changes are preserved. A sequence can cross midnight.

The dictionary describes playback duration and LMS time-before-next-interaction as
sums within sessions. They do not prove uninterrupted activity, so neither is added
to event start times. Continuity inside one aggregated activity row is unknowable.
`zombie_sequences.csv` gives qualifying start/end times, row counts and largest gaps.

## Phantom — duplicate recorded rows

Default: exact equality of **all columns**, including PIT_ID/PVT_ID, within the same
source. Same student/time but differing resources, counts or other values are not
full-row duplicates. `duplicate_groups.csv` includes recorded values, copy counts
and extra rows; student evidence lists matching students only.

If organisers mean identical activity with fresh surrogate IDs, explicitly run
`--ignore-columns PIT_ID PVT_ID` (or the relevant columns). This changes equality,
is recorded in the summary, and marks the run provisional. P_ID and TIMESTAMP cannot
be ignored. No date/time or numeric formatting normalization is used for exact rows.

## Ghost — drop in weekly row counts

Require at least 3 active weeks among academic weeks 1–4. Compare:
`later_rows / 48 < 0.10 * (early_rows / 4)`.
Count rows, **not** INTERACTION_COUNT or duration. Zero-activity weeks remain in
both denominators. Integer cross multiplication preserves the strict 10% boundary.

## Vampire — distinct active dates

Require `night_dates >21` AND `night_dates >day_dates`. Count distinct dates per
category across both sources. A date can appear in both sets; repeated events do not
increase its count. Preserve the previous interpretation: night `(00:00,05:00]`, day
`(05:00,24:00]`. Exact midnight counts against the previous daytime date; 05:00 is night.

Default UTC follows the supplied Z timestamps. The guide/dictionary does not resolve
UTC versus UK local time or every endpoint detail. These are explicit assumptions,
not a confirmed organiser ruling. Set `--timezone Europe/London` if UK local clock
time is intended; changing timezones can alter date counts. Original timestamp strings
are not used as lexicographic substitutes for parsed time.

## Undead Student — after deregistration

Supply `--persons` with P_ID and `deregistration_date`. The dictionary misspells this
as `deregristration_date`; both spellings are supported. If both contain different
non-null dates, validation fails. Null deregistration dates do not qualify. Duplicate
person keys and missing person context fail instead of multiplying/dropping events.

Flag source `DATE > deregistration_date`, not activity on the same date: a date-only
withdrawal field does not specify a withdrawal time. Evidence includes the number,
first and last dates of activity after deregistration. This is a DATE-key comparison,
not a guess about the time of withdrawal.

## Doppelgänger — identical recorded histories

Compare each student's complete multiset of LMS and video rows after removing only
identity/surrogate fields `P_ID`, `PVT_ID`, `PIT_ID`, `LOGIN_ID`. Source, normalized UTC
timestamp, resource, date and all other recorded fields remain. Multiplicity matters.
Different durations or an extra event break equality. Other numeric strings are
compared as recorded; approximate matches are not claimed.

Disk-sorted, length-framed SHA-256 fingerprints identify candidate groups, then full
ordered rows verify equality: a hash collision alone cannot produce a match. All
members appear once in findings, including **both IDs** in a pair. `matching_groups.csv`
lists membership and sizes without expanding every possible pair in large groups.

Default `--min-events 1` imposes no unofficial activity-count cutoff. A one-event
match may be ordinary shared behaviour; raise this configurable confidence filter
if justified. A conservative exact-history detector can miss shifted/approximate
copies. These are observed patterns, not confirmed planted monster labels.

## Werewolf — provisional heuristic

The guide says only “spikes in activity throughout the Autumn and Spring Terms”.
It supplies no numeric cutoff. All Werewolf output is **PROVISIONAL**, even without
`--sample` (findings include a `Status` column). The method counts rows per academic week and term, with zero weeks
included in the term baseline. A spike meets:

`weekly_rows >= max(min_spike_rows, spike_multiplier * term_mean_weekly_rows)`.

Require separated spike weeks in **both** terms. Defaults are:

- `--spike-multiplier 3`
- `--min-spike-rows 20`
- `--min-spike-weeks 2` per term
- `--min-spike-gap 2` between selected academic week numbers

All four are configurable, invented heuristic settings, **not official thresholds**.
`spike_weeks.csv` records counts, baseline and threshold. Student evidence lists the
separated weeks chosen greedily in date order. Use checked HUNT labels to assess and
tune the method; do not claim it detects all official Werewolves.

## Web Crawler — distinct resources in a rolling window

Flag **>200** distinct `(source,resource_id)` keys in a window with elapsed span
**<=12 hours**. Exactly 200 fails. Both endpoints are inclusive; an event exactly
12 hours earlier remains included. LMS item '123' and video '123' are distinct
resources; repeated accesses to either count once within the window.

Two sorted disk cursors and disk-backed resource reference counts prevent a busy
12-hour window from requiring every activity row in RAM. Evidence records the peak
count and its window. The guide's “items or videos” is interpreted as distinct
resources combined across sources, rather than event row counts.

## Shape-shifter — supplementary programme assignments required

The standard schema contains modules, registrations and departments but **no dated
programme assignments**. Those cannot verify a programme switch. The script requires
`--programme-history` with supplementary `P_ID,EFFECTIVE_DATE,PROGRAMME_ID` columns.
Use `--date-column` and `--programme-column` for alternative names. A file containing
only module/department IDs fails validation. No department proxy is presented as a
programme switch.

Records must mean successive single-programme assignments effective on those dates.
Within the selected calendar year, flag a change between successive dated assignments.
Repeated records/same programme do not create switches. Conflicting programmes for
one student on the same date make that student's history ambiguous: list the date
in `exceptions.csv` and exclude the student from findings. Evidence includes observed
changes and the previous observation date; it does not invent an effective start for
the prior assignment. A change before the year boundary is not inferred.

Without this supplementary data, Shape-shifter remains an **external data limitation**,
not a configured detector ready to analyse the standard dataset. The synthetic example
merely demonstrates its contract.
