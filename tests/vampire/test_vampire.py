import unittest
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from monsters.vampire.detector import VampireDetector
from shared.time_utils import timestamp_us


def classify(stamps, zone="UTC"):
    detector = VampireDetector(ZoneInfo(zone))
    for i, stamp in enumerate(stamps):
        detector.add(timestamp_us(stamp, None), None, "LMS" if i % 2 else "video")
    return detector.finish()


def dates(count, clock="02:00:00"):
    return [f"{date(2024, 1, 1) + timedelta(days=n)}T{clock}Z" for n in range(count)]


class VampireTests(unittest.TestCase):
    def test_twenty_one_fails_twenty_two_passes(self):
        self.assertFalse(classify(dates(21)).matched)
        self.assertTrue(classify(dates(22)).matched)

    def test_distinct_dates_not_number_of_events(self):
        result = classify(dates(1) * 100)
        self.assertFalse(result.matched)
        self.assertEqual(result.evidence["night_days"], 1)

    def test_night_day_tie_fails_and_same_date_can_count_in_both(self):
        result = classify(dates(22) + dates(22, "12:00:00"))
        self.assertFalse(result.matched)
        self.assertEqual(result.evidence, {"night_days": 22, "day_days": 22})
        self.assertTrue(classify(dates(22) + dates(21, "12:00:00")).matched)

    def test_midnight_counts_as_previous_day_five_am_counts_as_night(self):
        result = classify(["2024-01-02T00:00:00Z", "2024-01-02T00:00:00.000001Z",
                           "2024-01-02T05:00:00Z", "2024-01-02T05:00:00.000001Z"])
        self.assertEqual(result.evidence, {"night_days": 1, "day_days": 2})

    def test_timezone_conversion_changes_clock_and_date(self):
        stamp = ["2024-07-01T04:30:00Z"]
        self.assertEqual(classify(stamp).evidence["night_days"], 1)
        self.assertEqual(classify(stamp, "Europe/London").evidence["day_days"], 1)
        # UK midnight is the prior daytime date under the preserved convention.
        result = classify(["2024-07-01T22:00:00Z", "2024-07-01T23:00:00Z"], "Europe/London")
        self.assertEqual(result.evidence["day_days"], 1)
