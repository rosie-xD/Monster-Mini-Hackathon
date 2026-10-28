import unittest

from monsters.zombie.detector import ZombieDetector
from shared.time_utils import MINUTE, timestamp_us

START = timestamp_us("2023-10-02T23:00:00Z", None)


def classify(offsets):
    detector = ZombieDetector()
    for i, offset in enumerate(offsets):
        detector.add(START + offset, None, "LMS" if i % 2 else "video")
    return detector.finish()


class ZombieTests(unittest.TestCase):
    def test_exact_three_hours_fails_one_microsecond_over_passes(self):
        offsets = [i * 15 * MINUTE for i in range(13)]
        self.assertFalse(classify(offsets).matched)
        result = classify(offsets + [offsets[-1] + 1])
        self.assertTrue(result.matched)
        self.assertEqual(result.sequences[0]["max_gap_minutes"], 15)
        self.assertEqual(result.sequences[0]["activity_rows"], 14)

    def test_gap_over_fifteen_minutes_breaks_the_sequence(self):
        offsets = [i * 15 * MINUTE + (1 if i >= 7 else 0) for i in range(14)]
        self.assertFalse(classify(offsets).matched)

    def test_multiple_sequences_across_midnight_are_reported(self):
        first = [i * 15 * MINUTE for i in range(14)]
        second = [value + 400 * MINUTE for value in first]
        result = classify(first + second)
        self.assertEqual(len(result.sequences), 2)
        self.assertEqual(result.sequences[0]["end_utc"], "2023-10-03T02:15:00Z")
        self.assertEqual(result.evidence["longest_sequence_minutes"], 195)

    def test_duplicates_do_not_create_elapsed_time(self):
        result = classify([0] * 200)
        self.assertFalse(result.matched)
        self.assertEqual(result.evidence["longest_sequence_minutes"], 0)

    def test_unsorted_timestamps_fail(self):
        with self.assertRaisesRegex(ValueError, "sorted"):
            classify([MINUTE, 0])
