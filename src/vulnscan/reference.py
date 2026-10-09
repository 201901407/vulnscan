"""Rule-based conversion of a published vulnerability list into the reference format (ADR 0012)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

HEADING_RE = re.compile(r"^#{1,6}\s+(.*)")
ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)")
BOLD_LEAD_RE = re.compile(r"^(?:\*\*|__)(.+?)(?:\*\*|__)\s*(.*)$", re.DOTALL)


class ReferenceFormatError(Exception):
    pass


def parse_markdown_list(text: str, section: str | None = None) -> list[dict[str, str]]:
    """One entry per list item; the bold lead-in or the text before the first colon is the title."""
    items: list[str] = []
    in_section = section is None
    open_item = False
    for line in text.splitlines():
        heading = HEADING_RE.match(line)
        if heading:
            in_section = section is None or section.lower() in heading.group(1).lower()
            open_item = False
            continue
        if not in_section:
            continue
        item = ITEM_RE.match(line)
        if item:
            items.append(item.group(1).strip())
            open_item = True
        elif open_item and line.strip():
            items[-1] += " " + line.strip()
        else:
            open_item = False
    return [_entry(item) for item in items]


def _entry(item: str) -> dict[str, str]:
    bold = BOLD_LEAD_RE.match(item)
    if bold:
        title, description = bold.groups()
    else:
        title, colon, description = item.partition(": ")
        if not colon:
            title, description = item, ""
    title = title.strip().rstrip(":").strip()
    description = description.strip().lstrip(":-").strip()
    return {"title": title, "description": description or title}


PARSERS: dict[str, Callable[[str, str | None], list[dict[str, str]]]] = {
    ".md": parse_markdown_list,
    ".markdown": parse_markdown_list,
}


def convert(path: Path, section: str | None = None) -> list[dict[str, str]]:
    parser = PARSERS.get(path.suffix.lower())
    if parser is None:
        raise ReferenceFormatError(
            f"no converter for '{path.suffix}' files (supported: {', '.join(PARSERS)}); "
            "write the reference YAML by hand"
        )
    entries = parser(path.read_text(encoding="utf-8"), section)
    if not entries:
        raise ReferenceFormatError(f"no list items found in {path}; write the reference YAML by hand")
    return entries
