"""Vampire: >21 distinct night dates, exceeding distinct daytime dates."""

from datetime import timedelta
from zoneinfo import ZoneInfo

from shared.models import DetectionResult
from shared.time_utils import EPOCH, MINUTE

EVIDENCE_FIELDS = ("night_days", "day_days")


class VampireDetector:
    def __init__(self, zone=None):
        self.zone = zone if zone is not None else ZoneInfo("UTC")
        self.night_dates = set()
        self.day_dates = set()

    def add(self, instant, week, source):
        local = (EPOCH + timedelta(microseconds=instant)).astimezone(self.zone)
        clock = ((local.hour * 60 + local.minute) * 60 + local.second) * 1_000_000 + local.microsecond
        # Preserve the original interpretation: night (00:00,05:00], day (05:00,24:00].
        if 0 < clock <= 300 * MINUTE:
            self.night_dates.add(local.date())
        elif clock == 0:
            self.day_dates.add(local.date() - timedelta(days=1))
        else:
            self.day_dates.add(local.date())

    def finish(self):
        night, day = len(self.night_dates), len(self.day_dates)
        return DetectionResult(night > 21 and night > day, {"night_days": night, "day_days": day})
