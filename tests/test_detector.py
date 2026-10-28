import csv
import json
import random
import subprocess
import sys
import tempfile
import unittest
import zipfile
from datetime import date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from detect_monsters import (InputError, MINUTE, classify_student, csv_stream,
                             load_calendar, timestamp_us)

ROOT = Path(__file__).resolve().parents[1]
UTC = ZoneInfo("UTC")


def event(stamp, week=10, source="LMS"):
    return timestamp_us(stamp, None), week, source


class RuleTests(unittest.TestCase):
    def test_zombie_strict_duration_and_inclusive_gap(self):
        start = timestamp_us("2023-10-02T23:00:00Z", None)
        exact = [(start + n * 15 * MINUTE, 1, "LMS" if n % 2 else "video") for n in range(13)]
        self.assertFalse(classify_student(exact, UTC)[0]["Zombie"])
        metrics, sequences = classify_student(exact + [(exact[-1][0] + 1, 1, "video")], UTC)
        self.assertTrue(metrics["Zombie"])
        self.assertEqual(len(sequences), 1)
        self.assertEqual(sequences[0]["max_gap_minutes"], 15)
        self.assertEqual(sequences[0]["activity_rows"], 14)

    def test_zombie_gap_one_microsecond_too_large_breaks_sequence(self):
        start = timestamp_us("2023-10-02T00:00:00Z", None)
        events = [(start + n * 15 * MINUTE + (1 if n >= 7 else 0), 1, "video") for n in range(14)]
        self.assertFalse(classify_student(events, UTC)[0]["Zombie"])

    def test_ghost_zero_weeks_strict_ratio_and_three_active_weeks(self):
        # Early 10/4=2.5; later 12/48=.25 is EXACTLY 10%: must not match.
        early = [event("2023-10-02T12:00:00Z", w) for w in [1]*4 + [2]*3 + [3]*3]
        later = [event("2024-01-02T12:00:00Z", 14)] * 12
        metrics, _ = classify_student(early + later, UTC)
        self.assertFalse(metrics["Ghost"])
        self.assertEqual(metrics["early_weekly_average"], 2.5)
        self.assertEqual(metrics["later_weekly_average"], .25)
        self.assertTrue(classify_student(early + later[:-1], UTC)[0]["Ghost"])
        self.assertTrue(classify_student(early, UTC)[0]["Ghost"])
        self.assertFalse(classify_student(early[:7], UTC)[0]["Ghost"])

    def test_vampire_distinct_days_not_rows_and_strict_thresholds(self):
        start = date(2023, 10, 2)
        nights = [event(f"{start + timedelta(days=n)}T02:00:00Z") for n in range(22)]
        self.assertFalse(classify_student(nights[:21], UTC)[0]["Vampire"])
        self.assertFalse(classify_student(nights[:1] * 100, UTC)[0]["Vampire"])
        self.assertTrue(classify_student(nights, UTC)[0]["Vampire"])
        days = [event(f"{start + timedelta(days=n)}T12:00:00Z") for n in range(22)]
        metrics, _ = classify_student(sorted(nights + days), UTC)
        self.assertFalse(metrics["Vampire"])
        self.assertEqual((metrics["night_days"], metrics["day_days"]), (22, 22))
        self.assertTrue(classify_student(sorted(nights + days[:-1]), UTC)[0]["Vampire"])

    def test_vampire_midnight_and_five_am_boundaries(self):
        events = [event("2024-01-02T00:00:00Z"), event("2024-01-02T05:00:00Z"),
                  event("2024-01-02T05:00:00.000001Z")]
        metrics, _ = classify_student(events, UTC)
        self.assertEqual(metrics["night_days"], 1)
        self.assertEqual(metrics["day_days"], 2)

    def test_timezone_changes_vampire_clock_not_elapsed_time(self):
        events = [event("2024-07-01T04:30:00Z")]
        self.assertEqual(classify_student(events, UTC)[0]["night_days"], 1)
        self.assertEqual(classify_student(events, ZoneInfo("Europe/London"))[0]["night_days"], 0)
        self.assertEqual(timestamp_us("2024-10-27T01:30:00+01:00", None) + 60 * MINUTE,
                         timestamp_us("2024-10-27T01:30:00+00:00", None))

    def test_naive_timestamp_requires_explicit_timezone(self):
        with self.assertRaises(InputError):
            timestamp_us("2023-10-02T12:00:00", None)
        self.assertEqual(timestamp_us("2023-10-02T12:00:00", UTC),
                         timestamp_us("2023-10-02T12:00:00Z", None))
        with self.assertRaises(InputError):
            timestamp_us("2024-10-27T01:30:00", ZoneInfo("Europe/London"))


class FileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.calendar = self.path / "calendar.csv"
        self.start = date(2023, 10, 2)
        with self.calendar.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["DATE", "WEEK_NUMBER", "ACADEMIC_YEAR"])
            for n in range(364):
                writer.writerow([self.start + timedelta(days=n), n // 7 + 1, "2023"])

    def tearDown(self):
        self.temp.cleanup()

    def write_activity(self, name, records):
        path = self.path / name
        with path.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["TIMESTAMP", "P_ID", "DATE", "INTERACTION_COUNT"])
            writer.writerows((stamp, pid, stamp[:10], 999) for pid, stamp in records)
        return path

    def cli(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "detect_monsters.py"), *map(str, args)],
                              capture_output=True, text=True, cwd=self.path)

    def test_full_cli_shuffled_combined_sources_zip_and_evidence(self):
        lms, video = [], []
        for n in range(3):
            lms.append(("ghost", f"{self.start + timedelta(days=7*n)}T12:00:00Z"))
        for n in range(14):
            # Both sources are necessary to bridge the 15-minute gaps.
            minutes = n * 15
            stamp = f"2023-10-03T{minutes // 60:02}:{minutes % 60:02}:00Z"
            (lms if n % 2 else video).append(("zombie", stamp))
        for n in range(22):
            video.append(("vampire", f"{self.start + timedelta(days=n)}T02:00:00Z"))
        lms += [("normal", "2024-01-02T12:00:00Z")] * 30
        random.Random(42).shuffle(lms)
        random.Random(43).shuffle(video)
        lms_path = self.write_activity("lms.csv", lms)
        video_path = self.write_activity("video.csv", video)
        archive_path = self.path / "video.zip"
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(video_path, "video.csv")
        output = self.path / "out"
        result = self.cli("--lms", lms_path, "--video", archive_path, "--calendar", self.calendar,
                          "--output", output, "--sample")
        self.assertEqual(result.returncode, 0, result.stderr)
        with (output / "findings.csv").open() as f:
            findings = {(r["Monster Type"], r["P_ID"]) for r in csv.DictReader(f)}
        self.assertEqual(findings, {("Ghost", "ghost"), ("Ghost", "vampire"),
                                    ("Zombie", "zombie"), ("Vampire", "vampire")})
        with (output / "zombie_sequences.csv").open() as f:
            sequences = list(csv.DictReader(f))
        self.assertEqual(len(sequences), 1)
        self.assertEqual(float(sequences[0]["duration_minutes"]), 195)
        summary = json.loads((output / "run_summary.json").read_text())
        self.assertTrue(summary["completed"])
        self.assertTrue(summary["provisional_sample"])
        self.assertEqual(summary["students_with_activity"], 4)
        self.assertEqual(summary["rows"]["LMS"]["included"], len(lms))
        self.assertEqual(list(output.glob("monster-*")), [])
        again = self.cli("--lms", lms_path, "--video", archive_path, "--calendar", self.calendar,
                         "--output", output)
        self.assertNotEqual(again.returncode, 0)
        self.assertIn("not empty", again.stderr)

    def test_byte_parts_preserve_split_utf8_and_rows(self):
        content = "P_ID,TIMESTAMP\nétudiant,2023-10-02T01:00:00Z\n".encode("utf-8-sig")
        cut = content.index("é".encode()) + 1
        parts = []
        for n, chunk in enumerate([content[:cut], content[cut:cut+7], content[cut+7:]]):
            path = self.path / f"part_{n}"
            path.write_bytes(chunk)
            parts.append(path)
        with csv_stream(parts, parts=True) as stream:
            self.assertEqual(stream.read(), content.decode("utf-8-sig"))
        video = self.write_activity("video.csv", [("other", "2023-10-02T12:00:00Z")])
        output = self.path / "parts-output"
        result = self.cli("--lms-parts", *reversed(parts), "--video", video,
                          "--monsters", "Zombie", "Vampire", "--output", output)
        self.assertEqual(result.returncode, 0, result.stderr)
        with (output / "student_evidence.csv").open() as f:
            evidence = list(csv.DictReader(f))
        self.assertEqual(len(evidence), 2)
        self.assertTrue(all(r["Ghost"] == "not run" for r in evidence))

    def test_calendar_requires_complete_weeks_and_unique_dates(self):
        calendar, year = load_calendar(self.calendar, None)
        self.assertEqual(year, "2023")
        self.assertEqual(len(calendar), 364)
        original = self.calendar.read_text()
        self.calendar.write_text("\n".join(original.splitlines()[:-7]) + "\n")
        with self.assertRaises(InputError):
            load_calendar(self.calendar, None)
        self.calendar.write_text(original + original.splitlines()[1] + "\n")
        with self.assertRaisesRegex(InputError, "duplicate DATE"):
            load_calendar(self.calendar, None)

    def test_bad_timestamp_fails_without_success_summary(self):
        lms = self.write_activity("bad.csv", [("bad", "broken")])
        video = self.write_activity("video.csv", [("ok", "2023-10-02T12:00:00Z")])
        output = self.path / "bad-output"
        result = self.cli("--lms", lms, "--video", video, "--monsters", "Zombie", "Vampire",
                          "--output", output)
        self.assertEqual(result.returncode, 2)
        self.assertIn("line 2", result.stderr)
        self.assertFalse((output / "run_summary.json").exists())
        self.assertEqual(list(output.glob("monster-*")), [])

    def test_missing_calendar_and_missing_headers_fail_clearly(self):
        lms = self.write_activity("lms.csv", [("ok", "2023-10-02T12:00:00Z")])
        video = self.write_activity("video.csv", [("ok", "2023-10-02T12:00:00Z")])
        result = self.cli("--lms", lms, "--video", video)
        self.assertEqual(result.returncode, 2)
        self.assertIn("requires --calendar", result.stderr)
        lms.write_text("ok,2023-10-02T12:00:00Z\n")
        result = self.cli("--lms", lms, "--video", video, "--monsters", "Zombie", "Vampire",
                          "--output", self.path / "headers-output")
        self.assertEqual(result.returncode, 2)
        self.assertIn("missing headers", result.stderr)

    def test_streaming_multiple_batches_preserves_every_row(self):
        lms = self.write_activity("lms.csv", (("repeated", "2024-01-02T12:00:00Z")
                                              for _ in range(100_001)))
        video = self.write_activity("video.csv", [("repeated", "2024-01-02T12:00:00Z")])
        output = self.path / "large-output"
        result = self.cli("--lms", lms, "--video", video, "--calendar", self.calendar,
                          "--output", output)
        self.assertEqual(result.returncode, 0, result.stderr)
        with (output / "student_evidence.csv").open() as f:
            evidence = list(csv.DictReader(f))
        self.assertEqual(len(evidence), 1)
        self.assertEqual(int(evidence[0]["activity_rows"]), 100_002)
        self.assertEqual(int(evidence[0]["later_rows"]), 100_002)
        self.assertEqual(int(evidence[0]["day_days"]), 1)
        self.assertEqual(float(evidence[0]["longest_sequence_minutes"]), 0)

    def test_activity_outside_calendar_fails_instead_of_being_dropped(self):
        lms = self.write_activity("lms.csv", [("outside", "2022-01-02T12:00:00Z")])
        video = self.write_activity("video.csv", [("ok", "2023-10-02T12:00:00Z")])
        result = self.cli("--lms", lms, "--video", video, "--calendar", self.calendar,
                          "--output", self.path / "outside-output")
        self.assertEqual(result.returncode, 2)
        self.assertIn("absent from calendar", result.stderr)


if __name__ == "__main__":
    unittest.main()
