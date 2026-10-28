#!/usr/bin/env python3
"""Run all monsters or a selected subset; see each monster folder for its own CLI."""

from shared.cli import main
# Keep the original public helpers importable for existing notebooks/tests.
from shared.calendar import load_calendar
from shared.data_loading import csv_stream
from shared.errors import InputError
from shared.pipeline import classify_student
from shared.time_utils import MINUTE, timestamp_us


if __name__ == "__main__":
    raise SystemExit(main())
