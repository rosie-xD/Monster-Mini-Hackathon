#!/usr/bin/env python3
"""Explainable, disk-backed Mini Monster Hack detector. Python 3.10+, no packages."""

import argparse
import csv
import io
import itertools
import json
import sqlite3
import sys
import tempfile
import zipfile
from collections import Counter
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
MINUTE = 60_000_000  # integer microseconds: preserve strict boundaries
MONSTERS = ("Ghost", "Zombie", "Vampire")


class InputError(ValueError):
    pass


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


def classify_student(events, zone, early_weeks=4, later_weeks=48):
    """Consume one student's time-ordered (timestamp, academic_week, source) rows."""
    weekly = Counter()
    night_dates, day_dates = set(), set()
    sources = Counter()
    sessions = []
    session_start = previous = None
    session_count = session_max_gap = longest = 0
    row_count = 0

    def finish_session():
        nonlocal longest
        if session_start is None:
            return
        span = previous - session_start
        longest = max(longest, span)
        if span > 180 * MINUTE:
            sessions.append({"start_utc": iso_time(session_start), "end_utc": iso_time(previous),
                             "duration_minutes": span / MINUTE, "activity_rows": session_count,
                             "max_gap_minutes": session_max_gap / MINUTE})

    for instant, week, source in events:
        row_count += 1
        sources[source] += 1
        if week is not None:
            weekly[week] += 1
        local = (EPOCH + timedelta(microseconds=instant)).astimezone(zone)
        clock = ((local.hour * 60 + local.minute) * 60 + local.second) * 1_000_000 + local.microsecond
        # Literal guide intervals: night (00:00, 05:00], day (05:00, 24:00].
        if 0 < clock <= 300 * MINUTE:
            night_dates.add(local.date())
        elif clock == 0:
            day_dates.add(local.date() - timedelta(days=1))
        else:
            day_dates.add(local.date())
        gap = 0 if previous is None else instant - previous
        if previous is not None and gap < 0:
            raise ValueError("events must be sorted by timestamp")
        if previous is None or gap > 15 * MINUTE:
            finish_session()
            session_start, session_count, session_max_gap = instant, 1, 0
        else:
            session_count += 1
            session_max_gap = max(session_max_gap, gap)
        previous = instant
    finish_session()
    early = sum(weekly[w] for w in range(1, 5))
    later = sum(count for w, count in weekly.items() if w > 4)
    active = sum(weekly[w] > 0 for w in range(1, 5))
    # Cross multiplication keeps the strict <10% boundary exact.
    ghost = active >= 3 and 10 * later * early_weeks < early * later_weeks
    vampire = len(night_dates) > 21 and len(night_dates) > len(day_dates)
    return {
        "activity_rows": row_count, "lms_rows": sources["LMS"], "video_rows": sources["video"],
        "early_active_weeks": active, "early_rows": early, "later_rows": later,
        "early_weekly_average": early / early_weeks, "later_weekly_average": later / later_weeks,
        "later_to_early_ratio": (later * early_weeks / (early * later_weeks)) if early else "",
        "longest_sequence_minutes": longest / MINUTE, "qualifying_zombie_sequences": len(sessions),
        "night_days": len(night_dates), "day_days": len(day_dates),
        "Ghost": ghost, "Zombie": bool(sessions), "Vampire": vampire,
    }, sessions


def write_results(connection, output, zone, monsters):
    counts = Counter({name: 0 for name in monsters})
    students = 0
    with (open(output / "findings.csv", "w", newline="") as findings_file,
          open(output / "student_evidence.csv", "w", newline="") as evidence_file,
          open(output / "zombie_sequences.csv", "w", newline="") as sessions_file):
        findings = csv.writer(findings_file)
        findings.writerow(["Monster Type", "P_ID"])
        sessions_writer = csv.DictWriter(sessions_file, fieldnames=["P_ID", "start_utc", "end_utc",
                                                                 "duration_minutes", "activity_rows",
                                                                 "max_gap_minutes"])
        sessions_writer.writeheader()
        evidence_writer = None
        query = connection.execute("SELECT pid, instant, week, source FROM events ORDER BY pid, instant")
        for pid, group in itertools.groupby(query, key=lambda row: row[0]):
            students += 1
            metrics, sessions = classify_student((row[1:] for row in group), zone)
            for name in MONSTERS:
                if name not in monsters:
                    metrics[name] = "not run"
            if "Ghost" not in monsters:
                for name in ("early_active_weeks", "early_rows", "later_rows", "early_weekly_average",
                             "later_weekly_average", "later_to_early_ratio"):
                    metrics[name] = ""
            if evidence_writer is None:
                evidence_writer = csv.DictWriter(evidence_file, fieldnames=["P_ID", *metrics])
                evidence_writer.writeheader()
            evidence_writer.writerow({"P_ID": pid, **metrics})
            for name in monsters:
                if metrics[name]:
                    findings.writerow([name, pid])
                    counts[name] += 1
            if "Zombie" in monsters:
                for session in sessions:
                    sessions_writer.writerow({"P_ID": pid, **session})
    return students, dict(counts)


def parser():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    for source in ("lms", "video"):
        group = p.add_mutually_exclusive_group(required=True)
        group.add_argument(f"--{source}", nargs="+", type=Path, help="CSV/ZIP file(s), each with headers")
        group.add_argument(f"--{source}-parts", nargs="+", type=Path,
                           help="raw CSV byte parts from split; sorted by filename before reading")
    p.add_argument("--calendar", type=Path, help="full calendar CSV/ZIP; required for Ghost")
    p.add_argument("--academic-year", help="exact ACADEMIC_YEAR value; auto-selected if only one")
    p.add_argument("--monsters", nargs="+", choices=MONSTERS, default=list(MONSTERS))
    p.add_argument("--timezone", default="UTC", help="timezone for Vampire date/time boundaries")
    p.add_argument("--naive-timezone", help="explicit source timezone for timestamps without an offset")
    p.add_argument("--output", type=Path, default=Path("results"))
    p.add_argument("--sample", action="store_true", help="mark outputs provisional for incomplete input")
    return p


def run(args):
    zone = ZoneInfo(args.timezone)
    assumed_zone = ZoneInfo(args.naive_timezone) if args.naive_timezone else None
    if "Ghost" in args.monsters and not args.calendar:
        raise InputError("Ghost requires --calendar; use --monsters Zombie Vampire until it is available")
    if args.academic_year and not args.calendar:
        raise InputError("--academic-year requires --calendar")
    calendar, year = load_calendar(args.calendar, args.academic_year) if args.calendar else (None, None)
    sources = {}
    all_paths = []
    for source in ("lms", "video"):
        part_paths = getattr(args, source + "_parts")
        paths = sorted(part_paths) if part_paths else getattr(args, source)
        for path in paths:
            if not path.is_file():
                raise InputError(f"file not found: {path}")
        sources[source] = (paths, bool(part_paths))
        all_paths.extend(path.resolve() for path in paths)
    if len(all_paths) != len(set(all_paths)):
        raise InputError("an input file was supplied more than once")
    if args.output.exists() and any(args.output.iterdir()):
        raise InputError("output directory is not empty; choose a new --output directory")
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="monster-", dir=args.output) as temp:
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
            students, counts = write_results(connection, args.output, zone, args.monsters)
        finally:
            connection.close()
    report = {
        "completed": True, "provisional_sample": args.sample,
        "completeness": "Not automatically verifiable; complete student histories are required.",
        "academic_year": year, "timezone": args.timezone, "naive_timezone": args.naive_timezone,
        "monsters": args.monsters, "students_with_activity": students, "matches": counts,
        "rows": totals,
        "inputs": {source: [str(p) for p in paths] for source, (paths, _) in sources.items()},
        "calendar": str(args.calendar) if args.calendar else None,
        "rules": {
            "Ghost": "At least 3 active weeks in weeks 1–4; later rows/48 < 0.1*(early rows/4).",
            "Zombie": "Consecutive start timestamps with gaps <=15 minutes; span >180 minutes.",
            "Vampire": "Distinct night dates >21 and > distinct day dates; night (00:00,05:00], day (05:00,24:00].",
        },
        "assumptions": [
            "LMS and video rows are combined, preserving duplicate activity rows.",
            "Ghost uses DATE and calendar WEEK_NUMBER, including all zero-activity weeks.",
            "Zombie uses observed start timestamps, not aggregate duration fields.",
            "Exact midnight belongs to the previous daytime date; exact 05:00 is night.",
            "A date with both night and day activity counts in both sets.",
        ],
    }
    (args.output / "run_summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"output": str(args.output), "students": students, "matches": counts,
                      "provisional_sample": args.sample}, indent=2))


def main():
    args = parser().parse_args()
    try:
        run(args)
    except (InputError, OSError, ValueError, KeyError, sqlite3.Error, zipfile.BadZipFile) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
