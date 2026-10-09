from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable, TypeVar

from pydantic import BaseModel

from . import report
from .config import Config
from .evidence import EvidenceIndex, scored
from .ingest import load_app
from .lessons import LessonSet, generate, render, reserve
from . import llm
from .llm import LLMClient
from .match import MatchResult, match, score
from .names import AppNames
from .scan import ScanResult, scan
from .schema import as_reference, load_reference

log = logging.getLogger(__name__)

ARMS = ("baseline", "lessons")

Stage = TypeVar("Stage", bound=BaseModel)
ClientFactory = Callable[[str, float | None], LLMClient]


class RunDir:
    """One folder per run, one file per stage; an existing file is reused (ADR 0010)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.mkdir(parents=True, exist_ok=True)

    def stage(self, name: str, model: type[Stage], compute: Callable[[], Stage]) -> Stage:
        file = self.path / f"{name}.json"
        if file.exists():
            log.info("reusing %s", file.name)
            return model.model_validate_json(file.read_text())
        log.info("running %s", name)
        result = compute()
        file.write_text(result.model_dump_json(indent=2))
        return result


def run(config: Config, run_dir: Path, make_client: ClientFactory | None = None) -> dict:
    make_client = make_client or (
        lambda name, temperature: llm.make_client(
            name, config.models[name], config.llm.max_attempts, temperature, run_dir / "manual"
        )
    )
    # Build every client first so a missing key fails before any call is paid for.
    teacher = make_client(config.roles.teacher, None)
    judge = make_client(config.roles.judge, config.match.judge_temperature)
    students = {name: make_client(name, None) for name in config.roles.students}

    out = RunDir(run_dir)
    app = load_app(config.app.path, config.ingest)
    log.info("ingested %s", app.summary())
    evidence = EvidenceIndex(app)

    def checked_scan(client: LLMClient, lessons: list, source: str, held: int = 0) -> ScanResult:
        result = scan(
            client, app, config.categories, lessons, source, config.scan.chars_per_token, held
        )
        evidence.verify(result.findings, config.evidence)
        return result

    teacher_scan = out.stage("teacher.scan", ScanResult, lambda: checked_scan(teacher, [], "teacher"))
    teacher_findings = scored(teacher_scan.findings, config.evidence)

    lesson_set = out.stage(
        "lessons",
        LessonSet,
        lambda: generate(
            teacher, teacher_findings, AppNames.from_app(app), config.categories, config.lessons
        ),
    )
    (out.path / "lessons.txt").write_text(render(lesson_set.lessons))

    if config.app.reference:
        reference = load_reference(config.app.reference, config.categories)
        kind = "ground_truth"
    else:
        reference = as_reference(teacher_findings)
        kind = "teacher"

    def judged(name: str, result: ScanResult):
        findings = scored(result.findings, config.evidence)
        matched = out.stage(
            f"{name}.match",
            MatchResult,
            lambda: match(judge, reference, findings, config.match.batch_size),
        )
        return score(reference, matched)

    teacher_score = judged("teacher", teacher_scan) if kind == "ground_truth" else None

    student_reports = {}
    for name, client in students.items():
        held = reserve(
            lesson_set.lessons,
            client.budget,
            config.scan.lesson_budget_share,
            config.scan.chars_per_token,
        )
        arms = {}
        for arm in ARMS:
            scans, scores = [], []
            for number in range(1, config.scan.repeats + 1):
                stage = f"{name}.{arm}.{number}"
                lessons = lesson_set.lessons if arm == "lessons" else []
                result = out.stage(
                    f"{stage}.scan",
                    ScanResult,
                    lambda: checked_scan(client, lessons, stage, held),
                )
                scans.append(result)
                scores.append(judged(stage, result))
            arms[arm] = report.arm_stats(scans, scores)
        student_reports[name] = report.student_stats(arms["baseline"], arms["lessons"])

    summary = {
        "app": app.summary(),
        "reference": {"kind": kind, "entries": len(reference)},
        "teacher": report.teacher_stats(teacher_scan, teacher_score),
        "lessons": report.lesson_stats(lesson_set),
        "students": student_reports,
    }
    (out.path / "report.json").write_text(json.dumps(summary, indent=2))
    (out.path / "report.md").write_text(report.to_markdown(summary))
    return summary
