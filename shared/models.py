"""Small interface shared by the independent, per-student detectors."""

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class DetectionResult:
    matched: bool
    evidence: dict
    sequences: list[dict] = field(default_factory=list)


class StudentDetector(Protocol):
    """One instance per student; add each event, then call finish exactly once."""

    def add(self, instant: int, week: int | None, source: str) -> None:
        """instant is UTC microseconds; events arrive sorted; source is LMS or video."""
        ...

    def finish(self) -> DetectionResult:
        ...
