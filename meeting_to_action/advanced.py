"""Contracts for advanced, single-meeting analysis and interaction."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class QualitySeverity(StrEnum):
    INFO = "info"
    REVIEW = "review"
    CONFLICT = "conflict"


class TimelineKind(StrEnum):
    TRANSCRIPT = "transcript"
    ACTION = "action"
    DECISION = "decision"
    QUESTION = "question"


class TranscriptSegment(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    speaker: str | None = None
    locale: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def end_must_follow_start(self) -> "TranscriptSegment":
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        return self


class ContextDocument(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    filename: str = Field(min_length=1)
    text: str = Field(min_length=1)
    content_hash: str = Field(min_length=1)


class ContextCitation(BaseModel):
    model_config = ConfigDict(frozen=True)

    document_id: str = Field(min_length=1)
    quote: str = Field(min_length=1)
    section: str | None = None


class QualityFinding(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str = Field(min_length=1)
    severity: QualitySeverity
    title: str = Field(min_length=1)
    detail: str = Field(min_length=1)
    record_ids: list[str] = Field(default_factory=list)
    line_numbers: list[int] = Field(default_factory=list)
    context_citations: list[ContextCitation] = Field(default_factory=list)


class CorrectionEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    changed_at: datetime
    actor: str = Field(min_length=1)
    record_type: str = Field(min_length=1)
    record_id: str = Field(min_length=1)
    field: str = Field(min_length=1)
    before: Any = None
    after: Any = None


class TimelineEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    kind: TimelineKind
    label: str = Field(min_length=1)
    detail: str = Field(min_length=1)
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, ge=0)
    speaker: str | None = None
    record_id: str | None = None
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_ranges(self) -> "TimelineEvent":
        if self.start_ms is not None and self.end_ms is not None and self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        if self.line_start is not None and self.line_end is not None and self.line_end < self.line_start:
            raise ValueError("line_end must be greater than or equal to line_start")
        return self