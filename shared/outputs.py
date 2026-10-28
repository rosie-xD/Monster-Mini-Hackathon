"""Consistent findings/evidence CSVs for single or combined runs."""

import csv
import itertools
from collections import Counter

from shared.pipeline import EVIDENCE_FIELDS, MONSTERS, classify_student


def write_results(connection, output, zone, monsters):
    counts = Counter({name: 0 for name in monsters})
    students = 0
    with (open(output / "findings.csv", "w", newline="", encoding="utf-8") as findings_file,
          open(output / "student_evidence.csv", "w", newline="", encoding="utf-8") as evidence_file,
          open(output / "zombie_sequences.csv", "w", newline="", encoding="utf-8") as sessions_file):
        findings = csv.writer(findings_file)
        findings.writerow(["Monster Type", "P_ID"])
        sessions_writer = csv.DictWriter(sessions_file, fieldnames=["P_ID", "start_utc", "end_utc",
                                                                 "duration_minutes", "activity_rows",
                                                                 "max_gap_minutes"])
        sessions_writer.writeheader()
        evidence_writer = csv.DictWriter(evidence_file, fieldnames=[
            "P_ID", "activity_rows", "lms_rows", "video_rows", *EVIDENCE_FIELDS, *MONSTERS,
        ])
        evidence_writer.writeheader()
        # One indexed scan for all selected monsters. No per-detector SQL or data copy.
        query = connection.execute("SELECT pid, instant, week, source FROM events ORDER BY pid, instant")
        for pid, group in itertools.groupby(query, key=lambda row: row[0]):
            students += 1
            metrics, sessions = classify_student((row[1:] for row in group), zone, monsters=monsters)
            evidence_writer.writerow({"P_ID": pid, **metrics})
            for name in monsters:
                if metrics[name]:
                    findings.writerow([name, pid])
                    counts[name] += 1
            for session in sessions:
                sessions_writer.writerow({"P_ID": pid, **session})
    return students, dict(counts)
