"""Explainable, deterministic quality and conflict analysis."""

import re

from meeting_to_action.advanced import ContextCitation, ContextDocument, QualityFinding, QualitySeverity
from meeting_to_action.models import MeetingExtraction

WORD = re.compile(r"[a-z0-9]+")
STOP_WORDS = {"a", "an", "and", "for", "in", "of", "on", "the", "to", "will"}


def _tokens(value: str) -> set[str]:
    return {token for token in WORD.findall(value.lower()) if token not in STOP_WORDS}


def _context_citation(text: str, documents: list[ContextDocument]) -> ContextCitation | None:
    target = _tokens(text)
    if not target:
        return None
    best: tuple[float, ContextDocument, str] | None = None
    for document in documents:
        for section in filter(None, (line.strip() for line in document.text.splitlines())):
            overlap = len(target & _tokens(section)) / len(target)
            if best is None or overlap > best[0]:
                best = (overlap, document, section)
    if best is None or best[0] < 0.4:
        return None
    return ContextCitation(document_id=best[1].id, quote=best[2][:500])


def analyze_quality(
    extraction: MeetingExtraction,
    context_documents: list[ContextDocument] | None = None,
) -> list[QualityFinding]:
    documents = context_documents or []
    findings: list[QualityFinding] = []
    for action in extraction.actions:
        lines = sorted({line for evidence in action.evidence for line in range(evidence.line_start, evidence.line_end + 1)})
        if not action.owner:
            findings.append(QualityFinding(
                code="missing-owner",
                severity=QualitySeverity.REVIEW,
                title="Action owner needs review",
                detail=f"{action.id} has no owner stated in its transcript evidence.",
                record_ids=[action.id],
                line_numbers=lines,
            ))
        if not action.deadline_text:
            findings.append(QualityFinding(
                code="missing-deadline",
                severity=QualitySeverity.REVIEW,
                title="Action deadline needs review",
                detail=f"{action.id} has no deadline stated in its transcript evidence.",
                record_ids=[action.id],
                line_numbers=lines,
            ))
        citation = _context_citation(action.task, documents)
        if citation:
            findings.append(QualityFinding(
                code="context-alignment",
                severity=QualitySeverity.INFO,
                title="Supporting context aligns with action",
                detail=f"{action.id} matches material in {citation.document_id}; transcript evidence remains authoritative.",
                record_ids=[action.id],
                line_numbers=lines,
                context_citations=[citation],
            ))

    for index, first in enumerate(extraction.actions):
        for second in extraction.actions[index + 1:]:
            first_tokens = _tokens(first.task)
            second_tokens = _tokens(second.task)
            if not first_tokens or len(first_tokens & second_tokens) / len(first_tokens | second_tokens) < 0.65:
                continue
            owner_conflict = first.owner and second.owner and first.owner.casefold() != second.owner.casefold()
            deadline_conflict = first.deadline_text and second.deadline_text and first.deadline_text.casefold() != second.deadline_text.casefold()
            if owner_conflict or deadline_conflict:
                detail = " and ".join(filter(None, (
                    "different owners" if owner_conflict else None,
                    "different deadlines" if deadline_conflict else None,
                )))
                findings.append(QualityFinding(
                    code="action-conflict",
                    severity=QualitySeverity.CONFLICT,
                    title="Potentially conflicting actions",
                    detail=f"{first.id} and {second.id} describe similar work with {detail}.",
                    record_ids=[first.id, second.id],
                    line_numbers=sorted({e.line_start for item in (first, second) for e in item.evidence}),
                ))
    return findings