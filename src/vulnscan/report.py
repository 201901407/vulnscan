from __future__ import annotations

from statistics import mean

from .lessons import LessonSet
from .match import Score
from .scan import ScanResult


def spread(values: list[float]) -> dict:
    return {"mean": mean(values), "min": min(values), "max": max(values), "runs": values}


def arm_stats(scans: list[ScanResult], scores: list[Score]) -> dict:
    precisions = [s.precision for s in scores if s.precision is not None]
    return {
        "recall": spread([s.recall for s in scores]),
        "precision": spread(precisions) if precisions else None,
        "findings": [len(scan.findings) for scan in scans],
        "calls": [scan.calls for scan in scans],
        "lessons_shown": sorted({i for scan in scans for used in scan.lessons_used for i in used}),
        "unverified": [_unverified(scan) for scan in scans],
        "failed_calls": sum(scan.failed_calls for scan in scans),
        "malformed": sum(scan.malformed for scan in scans),
    }


def student_stats(baseline: dict, lessons: dict) -> dict:
    """Lift is the difference of mean recall; overlapping ranges mean it may be noise (ADR 0004)."""
    before, after = baseline["recall"], lessons["recall"]
    return {
        "baseline": baseline,
        "lessons": lessons,
        "lift": after["mean"] - before["mean"],
        # One run per arm says nothing about run-to-run noise, so no verdict is given.
        "distinguishable": (
            after["min"] > before["max"] or before["min"] > after["max"]
            if min(len(before["runs"]), len(after["runs"])) > 1
            else None
        ),
    }


def teacher_stats(scan: ScanResult, score: Score | None) -> dict:
    return {
        "findings": len(scan.findings),
        "unverified": _unverified(scan),
        "failed_calls": scan.failed_calls,
        "malformed": scan.malformed,
        "recall": score.recall if score else None,
        "precision": score.precision if score else None,
        "missed": score.missed if score else None,
    }


def lesson_stats(lessons: LessonSet) -> dict:
    return {
        "kept": len(lessons.lessons),
        "dropped": [{"title": d.lesson.title, "terms": d.terms} for d in lessons.dropped],
        "uncovered_categories": lessons.uncovered_categories,
        "malformed": lessons.malformed,
        "failed": lessons.failed,
    }


def to_markdown(report: dict) -> str:
    reference = report["reference"]
    against_teacher = reference["kind"] == "teacher"
    lines = ["# Scan report", "", f"App package: `{report['app']['package']}`", ""]
    if against_teacher:
        lines += [
            f"Reference: the teacher's {reference['entries']} verified findings. "
            "Recall below is agreement with the teacher, not true recall.",
            "",
        ]
    else:
        lines += [f"Reference: {reference['entries']} ground-truth entries.", ""]

    teacher = report["teacher"]
    lines += ["## Teacher", "", f"- Findings: {teacher['findings']} ({teacher['unverified']} unverified)"]
    if teacher["recall"] is not None:
        lines += [
            f"- Recall: {_pct(teacher['recall'])}",
            f"- Precision: {_pct(teacher['precision'])}",
            f"- Missed: {', '.join(teacher['missed']) or 'none'}",
        ]

    lessons = report["lessons"]
    lines += ["", "## Lessons", "", f"- Kept: {lessons['kept']}", f"- Dropped by the leak guard: {len(lessons['dropped'])}"]
    lines += [f"  - {d['title']} (mentions {', '.join(d['terms'])})" for d in lessons["dropped"]]
    lines += [f"- Categories found but not taught: {', '.join(lessons['uncovered_categories']) or 'none'}"]
    if lessons["failed"]:
        lines += ["- Lesson generation returned no usable output."]

    lines += [
        "",
        "## Students",
        "",
        "| Student | Arm | Recall mean (min-max) | Precision mean (min-max) | Unverified per run |",
        "| --- | --- | --- | --- | --- |",
    ]
    for name, student in report["students"].items():
        for arm in ("baseline", "lessons"):
            stats = student[arm]
            lines.append(
                f"| {name} | {arm} | {_range(stats['recall'])} | {_range(stats['precision'])} "
                f"| {stats['unverified']} |"
            )
    lines += [""]
    for name, student in report["students"].items():
        shown = len(student["lessons"]["lessons_shown"])
        lines.append(
            f"- {name}: {shown} of {lessons['kept']} lessons were shown in at least one call; "
            f"calls per scan {student['lessons']['calls']}"
        )
    lines += ["", "## Recall lift", ""]
    for name, student in report["students"].items():
        verdict = {
            True: "ranges do not overlap",
            False: "ranges overlap, so this is not distinguishable from run-to-run noise",
            None: "one run per arm, so run-to-run noise is unknown",
        }[student["distinguishable"]]
        lines.append(f"- {name}: {student['lift'] * 100:+.1f} points ({verdict})")
    return "\n".join(lines) + "\n"


def _unverified(scan: ScanResult) -> int:
    return sum(1 for finding in scan.findings if finding.evidence_status == "unverified")


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _range(stats: dict | None) -> str:
    if stats is None:
        return "n/a"
    return f"{_pct(stats['mean'])} ({_pct(stats['min'])}-{_pct(stats['max'])})"
