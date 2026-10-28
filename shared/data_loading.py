"""Stream CSV, ZIP and split CSV inputs into the shared SQLite store."""

import csv
import io
import sys
import zipfile
from contextlib import contextmanager

from shared.errors import InputError
from shared.time_utils import parse_date, timestamp_us

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
