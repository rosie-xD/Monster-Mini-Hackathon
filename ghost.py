#!/usr/bin/env python3
"""Find Ghost students. Run: python3 ghost.py --help

Standalone Python 3.10+ script; no packages to install.
Rule: Active in at least 3 of weeks 1–4; later_rows/48 < 0.1*(early_rows/4).
"""

import argparse
import csv
import io
import itertools
import json
import sqlite3
import sys
import tempfile
import uuid
import zipfile
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
MINUTE = 60_000_000  # integer microseconds, preserving exact threshold boundaries

MONSTER = 'Ghost'
RULE = 'Active in at least 3 of weeks 1–4; later_rows/48 < 0.1*(early_rows/4).'


# 1. Detection rule — edit this section for your monster.

@dataclass
class DetectionResult:
    matched: bool
    evidence: dict
    sequences: list[dict] = field(default_factory=list)


EVIDENCE_FIELDS = (
    "early_active_weeks", "early_rows", "later_rows", "early_weekly_average",
    "later_weekly_average", "later_to_early_ratio",
)


class GhostDetector:
    def __init__(self, early_weeks=4, later_weeks=48):
        self.early_weeks = early_weeks
        self.later_weeks = later_weeks
        self.weekly = Counter()

    def add(self, instant, week, source):
        if week is None or not 1 <= week <= 52:
            raise ValueError("Ghost requires a validated academic week from 1 to 52")
        self.weekly[week] += 1

    def finish(self):
        early = sum(self.weekly[w] for w in range(1, 5))
        later = sum(count for week, count in self.weekly.items() if week > 4)
        active = sum(self.weekly[w] > 0 for w in range(1, 5))
        # Integer cross multiplication preserves strict <10%, without float rounding.
        matched = active >= 3 and 10 * later * self.early_weeks < early * self.later_weeks
        evidence = {
            "early_active_weeks": active, "early_rows": early, "later_rows": later,
            "early_weekly_average": early / self.early_weeks,
            "later_weekly_average": later / self.later_weeks,
            "later_to_early_ratio": (later * self.early_weeks / (early * self.later_weeks)) if early else "",
        }
        return DetectionResult(matched, evidence)



# 2. File reading and timestamp validation — keeps large datasets on disk.

class InputError(ValueError):
    pass


def parse_date(value):
    # Accept ISO dates and ISO date-time strings in the DATE field, without guessing locale.
    return date.fromisoformat(value[:10])



def timestamp_us(value, assumed_zone):
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        if assumed_zone is None:
            raise InputError("timestamp has no UTC offset; specify --naive-timezone if known")
        moment = moment.replace(tzinfo=assumed_zone)
        # Refuse ambiguous/nonexistent local wall times around daylight-saving changes.
        if (moment.utcoffset() != moment.replace(fold=1).utcoffset()
                or moment.astimezone(timezone.utc).astimezone(assumed_zone).replace(tzinfo=None)
                != moment.replace(tzinfo=None)):
            raise InputError("ambiguous/nonexistent local time: supply timestamps with offsets")
    delta = moment.astimezone(timezone.utc) - EPOCH
    return delta.days * 86_400_000_000 + delta.seconds * 1_000_000 + delta.microseconds



def iso_time(value):
    return (EPOCH + timedelta(microseconds=value)).isoformat().replace("+00:00", "Z")


class JoinedParts(io.RawIOBase):
    """Concatenate raw CSV byte chunks, even when a split cuts a UTF-8 character."""

    def __init__(self, paths):
        super().__init__()
        self.paths = iter(paths)
        self.current = None

    def readable(self):
        return True

    def readinto(self, buffer):
        while True:
            if self.current is None:
                path = next(self.paths, None)
                if path is None:
                    return 0
                self.current = open(path, "rb")
            size = self.current.readinto(buffer)
            if size:
                return size
            self.current.close()
            self.current = None

    def close(self):
        if self.current is not None:
            self.current.close()
        super().close()



@contextmanager
def csv_stream(paths, parts=False):
    if parts:
        with io.BufferedReader(JoinedParts(paths)) as raw:
            with io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as stream:
                yield stream
    elif zipfile.is_zipfile(paths[0]):
        with zipfile.ZipFile(paths[0]) as archive:
            names = [n for n in archive.namelist()
                     if n.lower().endswith(".csv") and not n.startswith("__MACOSX/")]
            if len(names) != 1:
                raise InputError(f"{paths[0]}: ZIP must contain exactly one CSV")
            with archive.open(names[0]) as raw:
                with io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as stream:
                    yield stream
    else:
        with open(paths[0], encoding="utf-8-sig", newline="") as stream:
            yield stream



def rows(stream, required, label):
    reader = csv.DictReader(stream)
    if not reader.fieldnames:
        raise InputError(f"{label}: empty file")
    reader.fieldnames = [name.strip() for name in reader.fieldnames]
    if len(reader.fieldnames) != len(set(reader.fieldnames)):
        raise InputError(f"{label}: duplicate column names")
    missing = set(required) - set(reader.fieldnames)
    if missing:
        raise InputError(f"{label}: missing headers {sorted(missing)}; use a CSV with headers")
    for row in reader:
        if None in row or any(value is None for value in row.values()):
            raise InputError(f"{label}, line {reader.line_num}: wrong number of columns")
        yield reader.line_num, {key: value.strip() for key, value in row.items()}



def ingest(connection, paths, parts, source, calendar, year, assumed_zone):
    totals = {"read": 0, "included": 0, "outside_selected_year": 0}
    groups = [paths] if parts else [[path] for path in paths]
    batch = []
    for group in groups:
        label = str(group[0]) + (" (joined parts)" if parts else "")
        with csv_stream(group, parts) as stream:
            required = ("P_ID", "TIMESTAMP", "DATE") if calendar else ("P_ID", "TIMESTAMP")
            for line, row in rows(stream, required, label):
                totals["read"] += 1
                try:
                    pid = row["P_ID"]
                    if not pid or pid.lower() in ("null", "nan"):
                        raise ValueError("missing P_ID")
                    instant = timestamp_us(row["TIMESTAMP"], assumed_zone)
                    week = None
                    if calendar:
                        day = parse_date(row["DATE"])
                        if day not in calendar:
                            raise ValueError(f"DATE {day} is absent from calendar")
                        event_year, week = calendar[day]
                        if event_year != year:
                            totals["outside_selected_year"] += 1
                            continue
                    batch.append((pid, instant, week, source))
                    totals["included"] += 1
                except ValueError as exc:
                    raise InputError(f"{label}, line {line}: {exc}") from exc
                if len(batch) >= 50_000:
                    connection.executemany("INSERT INTO events VALUES (?, ?, ?, ?)", batch)
                    connection.commit()
                    batch.clear()
                if totals["read"] % 500_000 == 0:
                    print(f"{source}: read {totals['read']:,} rows", file=sys.stderr)
    if batch:
        connection.executemany("INSERT INTO events VALUES (?, ?, ?, ?)", batch)
        connection.commit()
    if not totals["included"]:
        raise InputError(f"{source}: no activity in the selected scope")
    print(f"{source}: included {totals['included']:,} rows", file=sys.stderr)
    return totals


def load_calendar(path, selected_year):
    calendar = {}
    with csv_stream([path]) as stream:
        for line, row in rows(stream, ("DATE", "WEEK_NUMBER", "ACADEMIC_YEAR"), path):
            try:
                day = parse_date(row["DATE"])
                week = int(row["WEEK_NUMBER"])
                year = row["ACADEMIC_YEAR"]
                if not year or not 1 <= week <= 52:
                    raise ValueError("expected academic year and week 1–52")
                if day in calendar:
                    raise ValueError("duplicate DATE would make the calendar join ambiguous")
                calendar[day] = (year, week)
            except ValueError as exc:
                raise InputError(f"{path}, line {line}: {exc}") from exc
    years = {year for year, _ in calendar.values()}
    if selected_year is None:
        if len(years) != 1:
            raise InputError("calendar has zero/multiple academic years; set --academic-year")
        selected_year = next(iter(years))
    selected = {day: week for day, (year, week) in calendar.items() if year == selected_year}
    if set(selected.values()) != set(range(1, 53)):
        raise InputError("selected calendar must contain all 52 academic weeks, including 1–4")
    days = sorted(selected)
    if len(days) != (days[-1] - days[0]).days + 1:
        raise InputError("selected calendar has missing dates")
    week_days = Counter(selected.values())
    if any(week_days[w] != 7 for w in range(1, 52)) or week_days[52] < 7:
        raise InputError("calendar must contain seven days per week (week 52 may include extra year-end days)")
    if any(selected[b] < selected[a] or selected[b] > selected[a] + 1
           for a, b in zip(days, days[1:])):
        raise InputError("academic weeks must progress in date order")
    return calendar, selected_year



# 3. Output and command-line runner.

def write_results(connection, output, zone):
    students = matches = 0
    with (open(output / "findings.csv", "w", newline="", encoding="utf-8") as found_file,
          open(output / "student_evidence.csv", "w", newline="", encoding="utf-8") as evidence_file):
        found = csv.writer(found_file)
        found.writerow(["Monster Type", "P_ID"])
        evidence = csv.DictWriter(evidence_file, fieldnames=[
            "P_ID", "activity_rows", "lms_rows", "video_rows", *EVIDENCE_FIELDS, MONSTER])
        evidence.writeheader()
        session_file = None
        try:
            if MONSTER == "Zombie":
                session_file = open(output / "zombie_sequences.csv", "w", newline="", encoding="utf-8")
                sequences = csv.DictWriter(session_file, fieldnames=[
                    "P_ID", "start_utc", "end_utc", "duration_minutes", "activity_rows", "max_gap_minutes"])
                sequences.writeheader()
            cursor = connection.execute("SELECT pid, instant, week, source FROM events ORDER BY pid, instant")
            for pid, events in itertools.groupby(cursor, key=lambda row: row[0]):
                students += 1
                detector = GhostDetector()
                counts = Counter()
                for _, instant, week, source in events:
                    counts[source] += 1
                    detector.add(instant, week, source)
                result = detector.finish()
                evidence.writerow({"P_ID": pid, "activity_rows": sum(counts.values()),
                                   "lms_rows": counts["LMS"], "video_rows": counts["video"],
                                   **result.evidence, MONSTER: result.matched})
                if result.matched:
                    matches += 1
                    found.writerow([MONSTER, pid])
                if session_file:
                    for sequence in result.sequences:
                        sequences.writerow({"P_ID": pid, **sequence})
        finally:
            if session_file:
                session_file.close()
    return students, matches


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    for source in ("lms", "video"):
        group = p.add_mutually_exclusive_group(required=True)
        group.add_argument(f"--{source}", nargs="+", type=Path, help="CSV or ZIP file(s) with headers")
        group.add_argument(f"--{source}-parts", nargs="+", type=Path, help="all raw CSV byte parts from split")
    p.add_argument("--calendar", type=Path, required=MONSTER == "Ghost",
                   help="complete calendar CSV/ZIP; required for Ghost, optional year filter otherwise")
    p.add_argument("--academic-year", help="exact calendar ACADEMIC_YEAR value if it contains multiple years")
    p.add_argument("--timezone", default="UTC", help="Vampire clock timezone, e.g. Europe/London; default UTC")
    p.add_argument("--naive-timezone", help="source timezone for timestamps that lack a UTC offset")
    p.add_argument("--output", type=Path, help="new results folder; defaults to a unique folder")
    p.add_argument("--sample", action="store_true", help="mark results as provisional for incomplete data")
    args = p.parse_args(argv)
    try:
        run(args)
    except (ValueError, OSError, KeyError, sqlite3.Error, zipfile.BadZipFile) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


def run(args):
    zone = ZoneInfo(args.timezone)
    assumed_zone = ZoneInfo(args.naive_timezone) if args.naive_timezone else None
    if args.academic_year and not args.calendar:
        raise InputError("--academic-year requires --calendar")
    calendar, year = load_calendar(args.calendar, args.academic_year) if args.calendar else (None, None)
    sources, seen = {}, set()
    for source in ("lms", "video"):
        parts = getattr(args, source + "_parts")
        paths = sorted(parts) if parts else getattr(args, source)
        for path in paths:
            if not path.is_file():
                raise InputError(f"file not found: {path}")
            if path.resolve() in seen:
                raise InputError(f"input supplied more than once: {path}")
            seen.add(path.resolve())
        sources[source] = (paths, bool(parts))
    if args.output is None:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        args.output = Path("results") / MONSTER.lower() / run_id
    try:
        args.output.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise InputError("output directory already exists; choose a new --output folder") from exc
    with tempfile.TemporaryDirectory(prefix="working-", dir=args.output) as temp:
        connection = sqlite3.connect(str(Path(temp) / "events.sqlite"))
        try:
            connection.execute("PRAGMA temp_store=FILE")
            connection.execute("PRAGMA cache_size=-65536")  # 64 MiB SQLite page cache
            connection.execute("CREATE TABLE events (pid TEXT, instant INTEGER, week INTEGER, source TEXT)")
            totals = {}
            for source, (paths, parts) in sources.items():
                label = "LMS" if source == "lms" else "video"
                totals[label] = ingest(connection, paths, parts, label, calendar, year, assumed_zone)
            print("Sorting activity on disk…", file=sys.stderr)
            connection.execute("CREATE INDEX activity_order ON events(pid, instant)")
            connection.commit()
            students, matches = write_results(connection, args.output, zone)
        finally:
            connection.close()
    report = {
        "completed": True, "monster": MONSTER, "rule": RULE,
        "provisional_sample": args.sample, "academic_year": year,
        "timezone": args.timezone, "naive_timezone": args.naive_timezone,
        "students_with_activity": students, "matches": matches, "rows": totals,
        "inputs": {source: [str(p) for p in paths] for source, (paths, _) in sources.items()},
        "calendar": str(args.calendar) if args.calendar else None,
        "notes": ["Complete student histories are required; completeness is not automatically verifiable.",
                  "LMS and video rows are combined, preserving duplicate rows.",
                  "Ghost includes zero-activity weeks and uses the calendar DATE key.",
                  "Zombie uses observed start timestamps, not summed playback/interaction durations.",
                  "Vampire: UTC by default; night (00:00,05:00], day (05:00,24:00].",
                  "Exact midnight belongs to the previous daytime date; 05:00 is night.",
                  "A date with both night/day activity counts in both sets."],
    }
    (args.output / "run_summary.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "monster": MONSTER,
                      "students": students, "matches": matches}, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
