from __future__ import annotations

import logging

from pydantic import BaseModel

from . import prompts
from .ingest import App, AppFile
from .lessons import select
from .llm import LLMClient, ModelOutputError, complete_json, estimate_tokens
from .schema import Finding, Lesson, parse_model_finding

log = logging.getLogger(__name__)

DEPENDENCIES_OMITTED = "(listed with part 1 only)"
MANIFEST_NOTE = (
    "- The manifest is repeated here for context only. Problems in the manifest itself "
    "are reported in part 1; do not report them again.\n"
)


class ScanResult(BaseModel):
    source: str
    model: str
    calls: int = 0
    failed_calls: int = 0
    malformed: int = 0
    lessons_used: list[list[str]] = []
    findings: list[Finding] = []


def scan(
    client: LLMClient,
    app: App,
    categories: dict[str, str],
    lessons: list[Lesson],
    source: str,
    chars_per_token: float,
    lesson_reserve: int = 0,
) -> ScanResult:
    """Scan the app with one model.

    Both arms of a student pass the same `lesson_reserve`, so they split the app
    into the same calls; only the lessons shown differ (ADR 0004, 0005).
    """
    system = prompts.load("scan_system")

    def user(files: str, part: int, parts: int, lesson_block: str) -> str:
        return prompts.fill(
            prompts.load("scan_user"),
            part=part,
            parts=parts,
            manifest_note="" if part == 1 else MANIFEST_NOTE,
            categories=prompts.category_list(categories),
            lessons=lesson_block,
            manifest_path=app.manifest.path,
            manifest=app.manifest.text,
            dependencies=_dependencies(app) if part == 1 else DEPENDENCIES_OMITTED,
            files=files,
        )

    overhead = estimate_tokens(system + user("", 1, 1, ""), chars_per_token)
    budget = client.budget - overhead - lesson_reserve
    if budget <= 0:
        raise ValueError(f"model '{client.name}': prompt overhead exceeds its input budget")
    batches = pack(app.sources + app.resources, budget, chars_per_token)
    if len(batches) > 1:
        log.info("%s: app split across %d calls for %s", source, len(batches), client.name)

    result = ScanResult(source=source, model=client.name)
    for part, batch in enumerate(batches, 1):
        result.calls += 1
        files = "\n".join(_render(file) for file in batch)
        visible = files + (app.manifest.text if part == 1 else "")
        shown = select(lessons, visible, lesson_reserve, chars_per_token)
        result.lessons_used.append([lesson.id for lesson in shown])
        try:
            reply = complete_json(
                client, system, user(files, part, len(batches), prompts.lesson_block(shown))
            )
        except ModelOutputError:
            log.warning("%s: call %d/%d gave no usable output", source, part, len(batches))
            result.failed_calls += 1
            continue
        for raw in reply.get("findings") or []:
            finding = parse_model_finding(raw, categories)
            if finding is None:
                result.malformed += 1
                continue
            finding.id = f"F{len(result.findings) + 1}"
            finding.source = source
            result.findings.append(finding)
    return result


def pack(files: list[AppFile], budget: int, chars_per_token: float) -> list[list[AppFile]]:
    """Group whole files into calls that fit the budget (ADR 0008).

    A file larger than the budget goes alone; splitting files would be added here.
    """
    batches: list[list[AppFile]] = []
    current: list[AppFile] = []
    used = 0
    for file in files:
        size = estimate_tokens(_render(file), chars_per_token)
        if size > budget:
            log.warning("%s exceeds the model's input budget and is sent alone", file.path)
        if current and used + size > budget:
            batches.append(current)
            current, used = [], 0
        current.append(file)
        used += size
    if current:
        batches.append(current)
    return batches


def _dependencies(app: App) -> str:
    lines = []
    if app.dependencies:
        lines += ["Resolved (group:artifact:version):", *app.dependencies]
    if app.unresolved_packages:
        lines += ["Unresolved (package names only, version unknown):", *app.unresolved_packages]
    return "\n".join(lines) or "none found"


def _render(file: AppFile) -> str:
    return f'<file path="{file.path}">\n{file.text}\n</file>'
