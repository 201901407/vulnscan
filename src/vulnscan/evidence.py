from __future__ import annotations

import re
from pathlib import PurePosixPath

from .config import EvidenceConfig
from .ingest import App
from .schema import Finding


# Models sometimes emit a newline as the two characters "\\n"; treat that as a line break too.
LINE_BREAK_RE = re.compile(r"\r?\n|\\[nr]")


def _squash(text: str) -> str:
    return "".join(text.split())


class EvidenceIndex:
    """Checks that a finding's quoted code exists in the app (ADR 0003)."""

    def __init__(self, app: App) -> None:
        self._files = {file.path: _squash(file.text) for file in app.files}

    def verify(self, findings: list[Finding], config: EvidenceConfig) -> None:
        if config.check == "off":
            return
        for finding in findings:
            finding.evidence_status = self._status(finding, config)

    def _status(self, finding: Finding, config: EvidenceConfig) -> str:
        lines = [
            squashed
            for line in LINE_BREAK_RE.split(finding.evidence)
            if len(squashed := _squash(line)) > config.trivial_line_chars
            and any(c.isalnum() for c in squashed)
        ]
        if not lines:
            return "unverified"
        named = [text for path, text in self._files.items() if _is_named(path, finding)]
        if _share_found(lines, named) >= config.min_match:
            return "verified"
        if _share_found(lines, self._files.values()) >= config.min_match:
            return "relocated"
        return "unverified"


def scored(findings: list[Finding], config: EvidenceConfig) -> list[Finding]:
    if config.check != "exclude":
        return findings
    return [f for f in findings if f.evidence_status != "unverified"]


def _is_named(path: str, finding: Finding) -> bool:
    for location in finding.locations:
        named = (location.file or "").strip("/")
        if named and (
            path == named
            or path.endswith("/" + named)
            or PurePosixPath(path).name == PurePosixPath(named).name
        ):
            return True
    return False


def _share_found(lines: list[str], texts) -> float:
    texts = list(texts)
    return sum(any(line in text for text in texts) for line in lines) / len(lines)
