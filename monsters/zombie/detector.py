"""Zombie: timestamp sequences >3 hours with no gap >15 minutes."""

from shared.models import DetectionResult
from shared.time_utils import MINUTE, iso_time

EVIDENCE_FIELDS = ("longest_sequence_minutes", "qualifying_zombie_sequences")


class ZombieDetector:
    def __init__(self):
        self.start = self.previous = None
        self.count = self.max_gap = self.longest = 0
        self.sequences = []

    def _finish_sequence(self):
        if self.start is None:
            return
        span = self.previous - self.start
        self.longest = max(self.longest, span)
        if span > 180 * MINUTE:
            self.sequences.append({
                "start_utc": iso_time(self.start), "end_utc": iso_time(self.previous),
                "duration_minutes": span / MINUTE, "activity_rows": self.count,
                "max_gap_minutes": self.max_gap / MINUTE,
            })

    def add(self, instant, week, source):
        gap = 0 if self.previous is None else instant - self.previous
        if gap < 0:
            raise ValueError("events must be sorted by timestamp")
        if self.previous is None or gap > 15 * MINUTE:
            self._finish_sequence()
            self.start, self.count, self.max_gap = instant, 1, 0
        else:
            self.count += 1
            self.max_gap = max(self.max_gap, gap)
        self.previous = instant

    def finish(self):
        self._finish_sequence()
        # Clear open session so a repeated finish does not duplicate evidence.
        self.start = None
        return DetectionResult(bool(self.sequences), {
            "longest_sequence_minutes": self.longest / MINUTE,
            "qualifying_zombie_sequences": len(self.sequences),
        }, self.sequences)
