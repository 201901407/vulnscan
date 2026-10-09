from __future__ import annotations

import json
import logging

from pydantic import BaseModel

from . import prompts
from .llm import LLMClient, ModelOutputError, complete_json
from .schema import Finding

log = logging.getLogger(__name__)

# Bookkeeping the judge must not see; `source` would reveal which arm a finding came from.
HIDDEN_FROM_JUDGE = {"source", "evidence_status"}


class Assignment(BaseModel):
    finding_id: str
    reference_id: str | None
    reason: str = ""


class MatchResult(BaseModel):
    assignments: list[Assignment] = []
    unanswered: int = 0


class Score(BaseModel):
    recall: float
    precision: float | None
    matched: list[str]
    missed: list[str]
    findings: int


def match(
    client: LLMClient,
    reference: list[Finding],
    findings: list[Finding],
    batch_size: int,
) -> MatchResult:
    """The judge assigns each finding to one reference entry or none (ADR 0001)."""
    system = prompts.load("judge_system")
    reference_ids = {entry.id for entry in reference}
    reference_json = _dump(reference)
    result = MatchResult()
    for start in range(0, len(findings), batch_size):
        batch = findings[start : start + batch_size]
        user = prompts.fill(
            prompts.load("judge_user"), reference=reference_json, findings=_dump(batch)
        )
        try:
            rows = complete_json(client, system, user).get("assignments") or []
        except ModelOutputError:
            log.warning("judge gave no usable output for %d findings", len(batch))
            rows = []
        answers = {str(row.get("finding_id")): row for row in rows if isinstance(row, dict)}
        for finding in batch:
            row = answers.get(finding.id)
            chosen = row.get("reference_id") if row else None
            if row is None or (chosen is not None and chosen not in reference_ids):
                result.unanswered += 1
                chosen, reason = None, "no valid answer from the judge"
            else:
                reason = str(row.get("reason") or "")
            result.assignments.append(
                Assignment(finding_id=finding.id, reference_id=chosen, reason=reason)
            )
    return result


def score(reference: list[Finding], result: MatchResult) -> Score:
    matched = {a.reference_id for a in result.assignments if a.reference_id}
    total = len(result.assignments)
    assigned = sum(1 for a in result.assignments if a.reference_id)
    return Score(
        recall=len(matched) / len(reference) if reference else 0.0,
        precision=assigned / total if total else None,
        matched=[entry.id for entry in reference if entry.id in matched],
        missed=[entry.id for entry in reference if entry.id not in matched],
        findings=total,
    )


def _dump(findings: list[Finding]) -> str:
    rows = [f.model_dump(exclude=HIDDEN_FROM_JUDGE, exclude_defaults=True) for f in findings]
    return json.dumps(rows, indent=2)
