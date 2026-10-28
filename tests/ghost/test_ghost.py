import unittest

from monsters.ghost.detector import GhostDetector


def classify(weeks):
    detector = GhostDetector()
    for index, week in enumerate(weeks):
        detector.add(index, week, "LMS" if index % 2 else "video")
    return detector.finish()


class GhostTests(unittest.TestCase):
    def test_three_early_weeks_with_no_later_activity(self):
        result = classify([1, 2, 3])
        self.assertTrue(result.matched)
        self.assertEqual(result.evidence["early_weekly_average"], .75)
        self.assertEqual(result.evidence["later_weekly_average"], 0)

    def test_two_active_weeks_are_insufficient_even_with_many_rows(self):
        self.assertFalse(classify([1] * 100 + [4] * 100).matched)

    def test_exact_ten_percent_fails_and_just_below_passes(self):
        early = [1] * 4 + [2] * 3 + [4] * 3
        self.assertFalse(classify(early + [5] * 12).matched)
        result = classify(early + [52] * 11)
        self.assertTrue(result.matched)
        self.assertEqual(result.evidence["later_weekly_average"], 11 / 48)

    def test_no_early_activity_is_not_a_ghost(self):
        result = classify([20, 21, 22])
        self.assertFalse(result.matched)
        self.assertEqual(result.evidence["later_to_early_ratio"], "")

    def test_requires_valid_calendar_week(self):
        for week in (None, 0, 53):
            with self.subTest(week=week), self.assertRaises(ValueError):
                GhostDetector().add(0, week, "LMS")
