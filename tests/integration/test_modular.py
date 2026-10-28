import contextlib
import csv
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from shared import cli
from shared.data_loading import ingest
from shared.pipeline import classify_student
from shared.time_utils import MINUTE, timestamp_us

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples" / "synthetic"


class ModularTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.args = ["--lms", str(EXAMPLES / "lms.csv"), "--video", str(EXAMPLES / "video.csv"),
                     "--calendar", str(EXAMPLES / "calendar.csv")]

    def tearDown(self):
        self.temp.cleanup()

    def execute(self, module=None, extra=()):
        command = [sys.executable]
        command += ["-m", module] if module else [str(ROOT / "detect_monsters.py")]
        env = dict(os.environ, PYTHONPATH=str(ROOT))
        result = subprocess.run(command + self.args + list(extra), cwd=self.path,
                                env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        return self.path / summary["output"]

    def findings(self, output):
        with (output / "findings.csv").open() as stream:
            return list(csv.DictReader(stream))

    def test_all_three_individual_clis_match_combined_and_expected_findings(self):
        combined = self.execute()
        expected = json.loads((EXAMPLES / "expected_findings.json").read_text())
        self.assertEqual(self.findings(combined), expected)
        for name in ("Ghost", "Zombie", "Vampire"):
            with self.subTest(monster=name):
                output = self.execute("monsters." + name.lower())
                self.assertEqual(self.findings(output), [r for r in expected if r["Monster Type"] == name])
                self.assertEqual(output.parent.name, name.lower())
                with (output / "student_evidence.csv").open() as f:
                    evidence = list(csv.DictReader(f))
                for row in evidence:
                    for other in {"Ghost", "Zombie", "Vampire"} - {name}:
                        self.assertEqual(row[other], "not run")

    def test_default_output_is_unique_and_explicit_existing_directory_is_protected(self):
        first = self.execute("monsters.zombie")
        before = (first / "findings.csv").read_bytes()
        second = self.execute("monsters.zombie")
        self.assertNotEqual(first, second)
        self.assertEqual((first / "findings.csv").read_bytes(), before)
        empty = self.path / "already-reserved"
        empty.mkdir()
        args = cli.parser().parse_args(self.args + ["--output", str(empty)])
        with self.assertRaisesRegex(ValueError, "already exists"):
            cli.run(args)

    def test_combined_run_ingests_each_source_once_and_scans_sorted_data_once(self):
        statements = []
        original_connect = sqlite3.connect

        def traced_connect(*args, **kwargs):
            conn = original_connect(*args, **kwargs)
            conn.set_trace_callback(statements.append)
            return conn

        args = cli.parser().parse_args(self.args + ["--output", str(self.path / "once")])
        with (patch("shared.cli.ingest", wraps=ingest) as loader,
              patch("shared.cli.sqlite3.connect", side_effect=traced_connect),
              contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO())):
            cli.run(args)
        self.assertEqual(loader.call_count, 2)
        self.assertEqual([call.args[3] for call in loader.call_args_list], ["LMS", "video"])
        self.assertEqual(sum(s.startswith("CREATE INDEX activity_order") for s in statements), 1)
        self.assertEqual(sum(s.startswith("SELECT pid, instant, week, source") for s in statements), 1)

    def test_single_detector_does_not_execute_other_monsters_or_reiterate_events(self):
        class Once:
            def __init__(self):
                self.used = False

            def __iter__(self):
                if self.used:
                    raise AssertionError("event stream was read twice")
                self.used = True
                start = timestamp_us("2024-01-01T12:00:00Z", None)
                yield from ((start + i * 15 * MINUTE, None, "LMS") for i in range(14))

        with (patch("shared.pipeline.GhostDetector", side_effect=AssertionError("Ghost ran")),
              patch("shared.pipeline.VampireDetector", side_effect=AssertionError("Vampire ran"))):
            metrics, sequences = classify_student(Once(), ZoneInfo("UTC"), monsters=["Zombie"])
        self.assertTrue(metrics["Zombie"])
        self.assertEqual(len(sequences), 1)
        self.assertEqual(metrics["night_days"], "")
        self.assertEqual(metrics["early_rows"], "")

    def test_repeated_selection_does_not_duplicate_findings(self):
        output = self.execute(extra=["--monsters", "Zombie", "Zombie"])
        self.assertEqual(len(self.findings(output)), 1)

    def test_multiple_complete_csv_inputs_equal_single_file(self):
        with (EXAMPLES / "lms.csv").open() as stream:
            rows = list(csv.reader(stream))
        for n, subset in enumerate((rows[1::2], rows[2::2])):
            with (self.path / f"lms{n}.csv").open("w", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(rows[0])
                writer.writerows(subset)
        self.args[1:2] = [str(self.path / "lms0.csv"), str(self.path / "lms1.csv")]
        self.assertEqual(self.findings(self.execute()),
                         json.loads((EXAMPLES / "expected_findings.json").read_text()))
