"""Typed records shared by extraction, review, chat, and evaluation."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Evidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    quote: str = Field(min_length=1)
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_line_range(self) -> "Evidence":
        if self.line_end < self.line_start:
            raise ValueError("line_end must be greater than or equal to line_start")
        return self


class ActionItem(BaseModel):
    id: str = Field(min_length=1)
    task: str = Field(min_length=1)
    owner: str | None = None
    deadline_text: str | None = Field(
        default=None,
        description="Verbatim deadline phrase, such as 'Friday' or 'September 25'",
    )
    deadline: date | None = Field(
        default=None,
        description="Normalized date only when the cited transcript explicitly states its year",
    )
    status: Literal["proposed", "confirmed", "completed"] = "proposed"
    evidence: list[Evidence] = Field(min_length=1)


class Decision(BaseModel):
    id: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    rationale: str | None = None
    evidence: list[Evidence] = Field(min_length=1)


class OpenQuestion(BaseModel):
    id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    owner: str | None = None
    evidence: list[Evidence] = Field(min_length=1)


class MeetingNote(BaseModel):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    evidence: list[Evidence] = Field(min_length=1)


class MeetingExtraction(BaseModel):
    title: str = Field(min_length=1)
    meeting_date: date | None = None
    summary: str = Field(min_length=1)
    notes: list[MeetingNote] = Field(default_factory=list)
    actions: list[ActionItem] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    open_questions: list[OpenQuestion] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)