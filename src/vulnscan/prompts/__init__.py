from __future__ import annotations

import re
from functools import cache
from importlib import resources

SLOT_RE = re.compile(r"\{\{(\w+)\}\}")


@cache
def load(name: str) -> str:
    return resources.files(__name__).joinpath(f"{name}.txt").read_text(encoding="utf-8")


def fill(template: str, **values: object) -> str:
    # Single pass, so slot-like text inside a value is never substituted again.
    return SLOT_RE.sub(lambda slot: str(values[slot.group(1)]), template)


def lesson_block(lessons) -> str:
    if not lessons:
        return ""
    return fill(load("scan_lessons"), lessons="\n\n".join(lesson.render() for lesson in lessons))


def category_list(categories: dict[str, str]) -> str:
    return "\n".join(f"- {name}: {description}" for name, description in categories.items())
