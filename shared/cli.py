"""One CLI and one disk-backed ingest/sort pipeline for every entry point."""

import argparse
import json
import sqlite3
import sys
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from shared.calendar import load_calendar
from shared.data_loading import ingest
from shared.errors import InputError
from shared.outputs import write_results
from shared.pipeline import MONSTERS

def parser(monster=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    for source in ("lms", "video"):
        group = p.add_mutually_exclusive_group(required=True)
        group.add_argument(f"--{source}", nargs="+", type=Path, help="CSV/ZIP file(s), each with headers")
        group.add_argument(f"--{source}-parts", nargs="+", type=Path,
                           help="raw CSV byte parts from split; sorted by filename before reading")
    p.add_argument("--calendar", type=Path, help="full calendar CSV/ZIP; required for Ghost")
    p.add_argument("--academic-year", help="exact ACADEMIC_YEAR value; auto-selected if only one")
    if monster is None:
        p.add_argument("--monsters", nargs="+", choices=MONSTERS, default=list(MONSTERS))
    else:
        p.set_defaults(monsters=[monster])
    p.add_argument("--timezone", default="UTC", help="timezone for Vampire date/time boundaries")
    p.add_argument("--naive-timezone", help="explicit source timezone for timestamps without an offset")
    p.add_argument("--output", type=Path, help="new output directory; default results/<selection>/<unique-run>")
    p.add_argument("--sample", action="store_true", help="mark outputs provisional for incomplete input")
    return p


def run(args):
    # Deterministic ordering, without duplicate findings if an option is repeated.
    args.monsters = [name for name in MONSTERS if name in args.monsters]
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
    if args.output is None:
        selection = "all" if len(args.monsters) == 3 else "-".join(args.monsters).lower()
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        args.output = Path("results") / selection / run_id
    # Reserve the run directory atomically, so concurrent runs cannot share it.
    try:
        args.output.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise InputError("output directory already exists (or is not empty); choose a new --output directory") from exc
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


def main(argv=None, monster=None):
    args = parser(monster).parse_args(argv)
    try:
        run(args)
    except (InputError, OSError, ValueError, KeyError, sqlite3.Error, zipfile.BadZipFile) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0
