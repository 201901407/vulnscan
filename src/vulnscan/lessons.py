from __future__ import annotations

import json
import logging
import re

from pydantic import BaseModel, ValidationError

from . import prompts
from .config import LessonConfig
from .llm import LLMClient, ModelOutputError, complete_json, estimate_tokens
from .names import AppNames
from .schema import OTHER, Finding, Lesson

log = logging.getLogger(__name__)

TOKEN_RE = re.compile(r"[A-Za-z_][\w.:-]*")
# camelCase, a dotted/qualified/hyphenated name, or an ALL_CAPS constant.
CODE_LIKE_RE = re.compile(r"[a-z][A-Z]|\w[.:_-]\w|^[A-Z][A-Z0-9_]{3,}$")
MIN_TAIL_CHARS = 5
LESSON_INPUT_FIELDS = {"id", "category", "type", "cwe", "severity", "title", "description", "evidence"}


class DroppedLesson(BaseModel):
    lesson: Lesson
    terms: list[str]


class LessonSet(BaseModel):
    lessons: list[Lesson] = []
    dropped: list[DroppedLesson] = []
    uncovered_categories: list[str] = []
    malformed: int = 0
    failed: bool = False


def generate(
    client: LLMClient,
    findings: list[Finding],
    names: AppNames,
    categories: dict[str, str],
    config: LessonConfig,
) -> LessonSet:
    """One teacher call turns its findings into general lessons (ADR 0009)."""
    result = LessonSet()
    if not findings:
        return result
    # Mask each value before JSON encoding: escapes such as \n would hide name boundaries.
    payload = [
        {
            key: names.mask(value) if isinstance(value, str) and key != "id" else value
            for key, value in finding.model_dump(include=LESSON_INPUT_FIELDS).items()
        }
        for finding in findings
    ]
    user = prompts.fill(
        prompts.load("lessons_user"),
        categories=prompts.category_list(categories),
        findings=json.dumps(payload, indent=2),
    )
    try:
        reply = complete_json(client, prompts.load("lessons_system"), user)
    except ModelOutputError:
        log.warning("lesson generation gave no usable output; continuing without lessons")
        result.failed = True
        reply = {}

    known_ids = {finding.id for finding in findings}
    for raw in reply.get("lessons") or []:
        try:
            lesson = Lesson.model_validate(raw)
        except ValidationError:
            result.malformed += 1
            continue
        lesson.id = f"L{len(result.lessons) + len(result.dropped) + 1}"
        lesson.category = lesson.category if lesson.category in categories else OTHER
        lesson.from_findings = [i for i in lesson.from_findings if i in known_ids]
        terms = names.leaks(lesson.render(), config.allow_terms)
        if terms:
            log.warning("dropped lesson '%s': mentions %s", lesson.title, terms)
            result.dropped.append(DroppedLesson(lesson=lesson, terms=terms))
        else:
            result.lessons.append(lesson)

    taught = {lesson.category for lesson in result.lessons}
    result.uncovered_categories = sorted({f.category for f in findings} - taught)
    return result


def reserve(lessons: list[Lesson], budget: int, share: float, chars_per_token: float) -> int:
    """Tokens set aside for lessons in every call: all of them if they fit the share, else the share."""
    return min(estimate_tokens(prompts.lesson_block(lessons), chars_per_token), int(budget * share))


def select(
    lessons: list[Lesson], text: str, allowance: int, chars_per_token: float
) -> list[Lesson]:
    """The lessons to show with one call (ADR 0005).

    All of them when they fit the allowance; otherwise those whose signals
    appear in the call's content, most matching signals first.
    """
    if estimate_tokens(prompts.lesson_block(lessons), chars_per_token) <= allowance:
        return lessons
    ranked = sorted(
        ((_hits(lesson, text), -position, lesson) for position, lesson in enumerate(lessons)),
        key=lambda item: item[:2],
        reverse=True,
    )
    chosen: list[Lesson] = []
    for hits, _, lesson in ranked:
        if hits == 0:
            break
        if estimate_tokens(prompts.lesson_block([*chosen, lesson]), chars_per_token) <= allowance:
            chosen.append(lesson)
    return [lesson for lesson in lessons if lesson in chosen]


def _hits(lesson: Lesson, text: str) -> int:
    return sum(any(term in text for term in _terms(signal)) for signal in lesson.signals)


def _terms(signal: str) -> set[str]:
    """Code-like tokens in a signal, which may be written as a phrase.

    `Log.d with password variables` yields `Log.d`; `android:minSdkVersion below 21`
    yields `android:minSdkVersion` and `minSdkVersion`. Plain words are ignored.
    """
    terms = set()
    for token in TOKEN_RE.findall(signal):
        token = token.strip(".:-")
        if not CODE_LIKE_RE.search(token):
            continue
        terms.add(token)
        tail = re.split(r"[.:]", token)[-1]
        if len(tail) >= MIN_TAIL_CHARS:
            terms.add(tail)
    return terms


def render(lessons: list[Lesson]) -> str:
    return "\n\n".join(lesson.render() for lesson in lessons)
