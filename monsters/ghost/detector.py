"""Ghost: early engagement followed by a strict fall below 10%."""

from collections import Counter

from shared.models import DetectionResult

EVIDENCE_FIELDS = (
    "early_active_weeks", "early_rows", "later_rows", "early_weekly_average",
    "later_weekly_average", "later_to_early_ratio",
)


class GhostDetector:
    def __init__(self, early_weeks=4, later_weeks=48):
        self.early_weeks = early_weeks
        self.later_weeks = later_weeks
        self.weekly = Counter()

    def add(self, instant, week, source):
        if week is None or not 1 <= week <= 52:
            raise ValueError("Ghost requires a validated academic week from 1 to 52")
        self.weekly[week] += 1

    def finish(self):
        early = sum(self.weekly[w] for w in range(1, 5))
        later = sum(count for week, count in self.weekly.items() if week > 4)
        active = sum(self.weekly[w] > 0 for w in range(1, 5))
        # Integer cross multiplication preserves strict <10%, without float rounding.
        matched = active >= 3 and 10 * later * self.early_weeks < early * self.later_weeks
        evidence = {
            "early_active_weeks": active, "early_rows": early, "later_rows": later,
            "early_weekly_average": early / self.early_weeks,
            "later_weekly_average": later / self.later_weeks,
            "later_to_early_ratio": (later * self.early_weeks / (early * self.later_weeks)) if early else "",
        }
        return DetectionResult(matched, evidence)
