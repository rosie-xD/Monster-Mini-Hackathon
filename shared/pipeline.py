"""Fan each student's single event stream out to the selected detectors."""

from collections import Counter

from monsters.ghost.detector import GhostDetector, EVIDENCE_FIELDS as GHOST_FIELDS
from monsters.zombie.detector import ZombieDetector, EVIDENCE_FIELDS as ZOMBIE_FIELDS
from monsters.vampire.detector import VampireDetector, EVIDENCE_FIELDS as VAMPIRE_FIELDS

MONSTERS = ("Ghost", "Zombie", "Vampire")
EVIDENCE_FIELDS = (*GHOST_FIELDS, *ZOMBIE_FIELDS, *VAMPIRE_FIELDS)


def classify_student(events, zone, early_weeks=4, later_weeks=48, monsters=MONSTERS):
    """Consume a sorted iterator once; unselected detectors are not instantiated."""
    selected = set(monsters)
    if not selected or selected - set(MONSTERS):
        raise ValueError("select at least one supported monster")
    detectors = {}
    if "Ghost" in selected:
        detectors["Ghost"] = GhostDetector(early_weeks, later_weeks)
    if "Zombie" in selected:
        detectors["Zombie"] = ZombieDetector()
    if "Vampire" in selected:
        detectors["Vampire"] = VampireDetector(zone)
    sources = Counter()
    count = 0
    previous = None
    for instant, week, source in events:
        if previous is not None and instant < previous:
            raise ValueError("events must be sorted by timestamp")
        previous = instant
        count += 1
        sources[source] += 1
        for detector in detectors.values():
            detector.add(instant, week, source)
    metrics = {"activity_rows": count, "lms_rows": sources["LMS"], "video_rows": sources["video"]}
    metrics.update(dict.fromkeys(EVIDENCE_FIELDS, ""))
    metrics.update(dict.fromkeys(MONSTERS, "not run"))
    sequences = []
    for name, detector in detectors.items():
        result = detector.finish()
        metrics.update(result.evidence)
        metrics[name] = result.matched
        if name == "Zombie":
            sequences = result.sequences
    return metrics, sequences
