#!/usr/bin/env python3
"""Standalone shape shifter detector. Python 3.10+, standard library only.

Run: python3 shape_shifter.py --help. See RULES.md for interpretation limits.
"""

import argparse
import csv
import hashlib
import io
import itertools
import json
import math
import sqlite3
import sys
import tempfile
import uuid
import zipfile
from collections import Counter
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
MINUTE = 60_000_000

MONSTER, SLUG = 'Shape-shifter', 'shape_shifter'
RULE = 'A change of recorded programme assignment on different effective dates within the selected academic year.'
METHOD, HEURISTIC = 'Dated single-programme assignment history; no department/module proxy', False
NOTES = ['The supplied dictionary/ERD has NO dated programme history. This script requires supplementary data.',
         'Required supplementary schema: P_ID, EFFECTIVE_DATE, PROGRAMME_ID (column names configurable).',
         'Records must represent successive single-programme assignments, not concurrent enrolments or module choices.',
         'Students with conflicting programmes on the same date are excluded as ambiguous and listed in exceptions.csv.',
         'Changes before the selected academic year are not inferred from rows outside that year.']


def add_options(parser):
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--programme-history',type=Path,help='supplementary dated assignments CSV/ZIP; absent from standard dataset')
    group.add_argument('--history-parts',nargs='+',type=Path,help='all split raw programme-history CSV parts')
    parser.add_argument('--date-column',default='EFFECTIVE_DATE')
    parser.add_argument('--programme-column',default='PROGRAMME_ID')


def validate_options(args):
    pass


def prepare(conn,args,calendar,year):
    conn.execute('CREATE TABLE history (pid TEXT,day TEXT,programme TEXT)')
    return {'standard_dataset_limitation':'No programme history in supplied dictionary/ERD; supplementary dated assignments required'}


def ingest_history(conn,args,calendar,year):
    paths=sorted(args.history_parts) if args.history_parts else [args.programme_history]
    stats=dict(read=0,included=0,outside_selected_year=0)
    batch=[]
    with csv_stream(paths,bool(args.history_parts)) as stream:
        for line,row in rows(stream,['P_ID',args.date_column,args.programme_column],str(paths[0])):
            stats['read']+=1
            try:
                pid=identifier(row['P_ID'],'P_ID')
                day=parse_date(row[args.date_column])
                programme=identifier(row[args.programme_column],args.programme_column)
                if day not in calendar:raise InputError(f'DATE {day} absent from calendar')
                if calendar[day][0]!=year:
                    stats['outside_selected_year']+=1;continue
                batch.append((pid,day.isoformat(),programme));stats['included']+=1
            except ValueError as exc:
                raise InputError(f'{paths[0]}, line {line}: {exc}') from exc
            if len(batch)>=50_000:
                conn.executemany('INSERT INTO history VALUES (?,?,?)',batch);conn.commit();batch.clear()
    if batch:conn.executemany('INSERT INTO history VALUES (?,?,?)',batch);conn.commit()
    if not stats['included']:raise InputError('No programme records in selected academic year')
    return {'programme_history':stats}


def detect(conn,args,calendar,year):
    conn.execute('CREATE INDEX history_order ON history(pid,day,programme)')
    conn.execute('CREATE TABLE ambiguous (pid TEXT PRIMARY KEY)')
    with output_csv(args,'exceptions.csv',['P_ID','effective_date','reason']) as exceptions:
        for pid,day in conn.execute('SELECT pid,day FROM history GROUP BY pid,day HAVING COUNT(DISTINCT programme)>1'):
            exceptions.writerow([pid,day,'Multiple programme assignments on same date; cannot establish a switch'])
            conn.execute('INSERT OR IGNORE INTO ambiguous VALUES (?)',(pid,))
    query=conn.execute('SELECT DISTINCT pid,day,programme FROM history ORDER BY pid,day,programme')
    students=matches=0
    with (output_csv(args,'findings.csv',['Monster Type','P_ID']) as findings,
          output_csv(args,'student_evidence.csv',['P_ID','status','distinct_programmes','switches','matched']) as evidence,
          output_csv(args,'programme_changes.csv',['P_ID','previous_observation_date','effective_date','from_programme','to_programme']) as changes):
        for pid,student in itertools.groupby(query,key=lambda r:r[0]):
            students+=1
            if conn.execute('SELECT 1 FROM ambiguous WHERE pid=?',(pid,)).fetchone():
                for _ in student:pass
                evidence.writerow([pid,'AMBIGUOUS',None,None,False]);continue
            previous_day=previous_programme=None;programmes=set();switches=0
            for _,day,programme in student:
                programmes.add(programme)
                if previous_programme is not None and programme!=previous_programme:
                    switches+=1;changes.writerow([pid,previous_day,day,previous_programme,programme])
                previous_day,previous_programme=day,programme
            evidence.writerow([pid,'dated assignments supplied',len(programmes),switches,bool(switches)])
            if switches:matches+=1;findings.writerow([MONSTER,pid])
    ambiguous=conn.execute('SELECT COUNT(*) FROM ambiguous').fetchone()[0]
    return students,matches,{'ambiguous_students_excluded':ambiguous,'requires_supplementary_programme_history':True}


# Standalone file/validation helpers.

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


def rows(stream, required, label):
    reader = csv.DictReader(stream)
    if not reader.fieldnames:
        raise InputError(f"{label}: empty file")
    reader.fieldnames = [h.strip() for h in reader.fieldnames]
    if len(set(reader.fieldnames)) != len(reader.fieldnames):
        raise InputError(f"{label}: duplicate headers")
    missing = set(required) - set(reader.fieldnames)
    if missing:
        raise InputError(f"{label}: missing headers {sorted(missing)}")
    for row in reader:
        if None in row or any(v is None for v in row.values()):
            raise InputError(f"{label}, line {reader.line_num}: wrong column count")
        yield reader.line_num, row  # Preserve original field values for exact matching.


def identifier(value, label):
    if not value.strip() or value.strip().lower() in ('null', 'none', 'nan'):
        raise InputError(f"missing {label}")
    return value


@contextmanager
def output_csv(args, filename, columns):
    with (args.output / filename).open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream)
        writer.writerow(columns)
        yield writer


def activity_paths(args):
    sources, seen = {}, set()
    for source in ('lms', 'video'):
        parts = getattr(args, source + '_parts')
        paths = sorted(parts) if parts else getattr(args, source)
        for path in paths:
            if not path.is_file():
                raise InputError(f"file not found: {path}")
            if path.resolve() in seen:
                raise InputError(f"input supplied twice: {path}")
            seen.add(path.resolve())
        sources[source] = (paths, bool(parts))
    return sources


def ingest_activity(conn, args, calendar, year):
    sources = activity_paths(args)
    assumed_zone = ZoneInfo(args.naive_timezone) if args.naive_timezone else None
    totals = {}
    for source, (paths, parts) in sources.items():
        stats = dict(read=0, included=0, outside_selected_year=0)
        batch = []
        for group in ([paths] if parts else [[p] for p in paths]):
            label = str(group[0])
            resource_column = 'LMS_ITEM_ID' if source == 'lms' else 'VIDEO_ID'
            required = ['P_ID', 'TIMESTAMP']
            if calendar or MONSTER == 'Undead Student':
                required.append('DATE')
            if MONSTER in ('Web Crawler', 'Doppelgänger'):
                required.append(resource_column)
            with csv_stream(group, parts) as stream:
                for line, row in rows(stream, required, label):
                    stats['read'] += 1
                    try:
                        pid = identifier(row['P_ID'], 'P_ID')
                        instant = timestamp_us(row['TIMESTAMP'], assumed_zone)
                        day = parse_date(row['DATE']) if 'DATE' in row else None
                        if calendar:
                            if day not in calendar:
                                raise InputError(f"DATE {day} is absent from calendar")
                            if calendar[day][0] != year:
                                stats['outside_selected_year'] += 1
                                continue
                        resource = None
                        if resource_column in row:
                            resource = identifier(row[resource_column], resource_column)
                        payload = None
                        if MONSTER in ('Phantom', 'Doppelgänger'):
                            ignored = set(args.ignore_columns)
                            content = {k: v for k, v in row.items() if k not in ignored}
                            if MONSTER == 'Doppelgänger':
                                content['TIMESTAMP'] = str(instant)
                                if day is not None:
                                    content['DATE'] = day.isoformat()
                            payload = json.dumps([source, content], sort_keys=True, ensure_ascii=False, separators=(',', ':'))
                        batch.append((pid, instant, day.isoformat() if day else None, resource, source, payload))
                        stats['included'] += 1
                    except ValueError as exc:
                        raise InputError(f"{label}, line {line}: {exc}") from exc
                    if len(batch) >= 50_000:
                        conn.executemany('INSERT INTO events VALUES (?,?,?,?,?,?)', batch)
                        conn.commit(); batch.clear()
                    if stats['read'] % 500_000 == 0:
                        print(f"{source}: read {stats['read']:,} rows", file=sys.stderr)
        if batch:
            conn.executemany('INSERT INTO events VALUES (?,?,?,?,?,?)', batch)
            conn.commit()
        if not stats['included']:
            raise InputError(f"{source}: no activity in selected scope")
        print(f"{source}: included {stats['included']:,} rows", file=sys.stderr)
        totals[source] = stats
    return totals


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    if MONSTER != 'Shape-shifter':
        for source in ('lms', 'video'):
            group = parser.add_mutually_exclusive_group(required=True)
            group.add_argument('--' + source, nargs='+', type=Path, help='CSV/ZIP file(s), each with headers')
            group.add_argument('--' + source + '-parts', nargs='+', type=Path, help='all split uncompressed CSV byte parts')
    parser.add_argument('--calendar', type=Path, required=MONSTER in ('Werewolf', 'Shape-shifter'))
    parser.add_argument('--academic-year', help='exact calendar ACADEMIC_YEAR; inferred for a single year')
    parser.add_argument('--naive-timezone', help='explicit source timezone if timestamps lack offsets')
    parser.add_argument('--output', type=Path, help='new output directory; defaults to a unique results folder')
    parser.add_argument('--sample', action='store_true', help='incomplete input; results are provisional')
    add_options(parser)
    args = parser.parse_args(argv)
    try:
        validate_options(args)
        if args.academic_year and not args.calendar:
            raise InputError('--academic-year requires --calendar')
        calendar, year = load_calendar(args.calendar, args.academic_year) if args.calendar else (None, None)
        if args.output is None:
            run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
            args.output = Path('results') / SLUG / run_id
        try:
            args.output.mkdir(parents=True, exist_ok=False)
        except FileExistsError as exc:
            raise InputError('output directory already exists; choose another --output') from exc
        with tempfile.TemporaryDirectory(prefix='working-', dir=args.output) as temp:
            conn = sqlite3.connect(str(Path(temp) / 'events.sqlite'))
            try:
                conn.execute('PRAGMA temp_store=FILE')
                conn.execute('PRAGMA cache_size=-65536')
                conn.execute('CREATE TABLE events (pid TEXT, instant INTEGER, day TEXT, resource TEXT, source TEXT, payload TEXT)')
                context = prepare(conn, args, calendar, year)
                totals = ingest_history(conn, args, calendar, year) if MONSTER == 'Shape-shifter' else ingest_activity(conn, args, calendar, year)
                students, matches, details = detect(conn, args, calendar, year)
            finally:
                conn.close()
        report = dict(completed=True, monster=MONSTER, method=METHOD,
                      provisional=bool(args.sample or HEURISTIC or (MONSTER == 'Phantom' and args.ignore_columns)), rule=RULE,
                      academic_year=year, students_with_records=students, matches=matches,
                      rows=totals, context=context, details=details,
                      parameters={k: [str(i) if isinstance(i,Path) else i for i in v] if isinstance(v,list) else str(v) if isinstance(v,Path) else v for k,v in vars(args).items()},
                      notes=NOTES + ['Input completeness is not automatically verifiable.',
                          'Only a completed run writes run_summary.json; disregard partial files after errors.'])
        (args.output/'run_summary.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(dict(output=str(args.output),monster=MONSTER,matches=matches,provisional=report['provisional']),indent=2))
        return 0
    except (ValueError, OSError, KeyError, sqlite3.Error, zipfile.BadZipFile) as exc:
        print(f'ERROR: {exc}',file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
