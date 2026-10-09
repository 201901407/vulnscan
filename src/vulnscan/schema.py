from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

OTHER = "other"
CWE_RE = re.compile(r"CWE-\d+")

Severity = Literal["critical", "high", "medium", "low", "info"]
EvidenceStatus = Literal["unchecked", "verified", "relocated", "unverified"]


class Location(BaseModel):
    model_config = ConfigDict(extra="ignore")

    file: str | None = None
    symbol: str | None = None
    line: int | None = None

    @field_validator("line", mode="before")
    @classmethod
    def _line(cls, value: Any) -> int | None:
        return value if isinstance(value, int) else None


class Finding(BaseModel):
    """One vulnerability, from a model or from a reference list (ADR 0002)."""

    model_config = ConfigDict(extra="ignore")

    id: str = ""
    source: str = ""
    title: str
    category: str = OTHER
    category_other: str | None = None
    type: str | None = None
    cwe: str | None = None
    severity: Severity | None = None
    locations: list[Location] = Field(default_factory=list)
    evidence: str = ""
    description: str
    extra: dict[str, Any] = Field(default_factory=dict)
    evidence_status: EvidenceStatus = "unchecked"

    @field_validator("severity", mode="before")
    @classmethod
    def _severity(cls, value: Any) -> Any:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("cwe", mode="before")
    @classmethod
    def _cwe(cls, value: Any) -> str | None:
        text = value.strip().upper() if isinstance(value, str) else ""
        return text if CWE_RE.fullmatch(text) else None

    @field_validator("locations", mode="before")
    @classmethod
    def _locations(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return [value]
        if isinstance(value, str):
            return [{"file": value}]
        return value or []

    def normalise_category(self, categories: dict[str, str]) -> None:
        label = self.category.strip().lower()
        if label in categories:
            self.category = label
        else:
            if label != OTHER and not self.category_other:
                self.category_other = self.category
            self.category = OTHER


def parse_model_finding(raw: Any, categories: dict[str, str]) -> Finding | None:
    """Validate a finding emitted by a model; None means malformed."""
    try:
        finding = Finding.model_validate(raw)
    except ValidationError:
        return None
    if not (finding.type and finding.severity and finding.locations and finding.evidence.strip()):
        return None
    finding.normalise_category(categories)
    return finding


def load_reference(path: Path, categories: dict[str, str]) -> list[Finding]:
    entries = yaml.safe_load(path.read_text()) or []
    reference = []
    for number, entry in enumerate(entries, 1):
        finding = Finding.model_validate(entry)
        finding.normalise_category(categories)
        finding.id = f"R{number}"
        reference.append(finding)
    return reference


def as_reference(findings: list[Finding]) -> list[Finding]:
    return [f.model_copy(update={"id": f"R{n}"}) for n, f in enumerate(findings, 1)]


class Lesson(BaseModel):
    """A general vulnerability pattern, free of app-specific detail (ADR 0005)."""

    model_config = ConfigDict(extra="ignore")

    id: str = ""
    category: str = OTHER
    cwe: str | None = None
    title: str
    pattern: str
    signals: list[str] = Field(default_factory=list)
    why: str
    not_when: str
    from_findings: list[str] = Field(default_factory=list)

    @field_validator("cwe", mode="before")
    @classmethod
    def _cwe(cls, value: Any) -> str | None:
        text = value.strip().upper() if isinstance(value, str) else ""
        return text if CWE_RE.fullmatch(text) else None

    def render(self) -> str:
        return "\n".join(
            [
                f"Lesson: {self.title}",
                f"Category: {self.category}",
                f"Look for: {self.pattern}",
                f"Signals: {', '.join(self.signals)}",
                f"Why: {self.why}",
                f"Not when: {self.not_when}",
            ]
        )
