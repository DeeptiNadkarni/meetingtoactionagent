import asyncio
from datetime import datetime, timezone

import pytest

from meeting_to_action import sft_enrichment
from meeting_to_action.models import ActionItem, Evidence, MeetingExtraction, MeetingNote
from meeting_to_action.sft_enrichment import (
    generate_enrichment_drafts,
    merge_human_annotations,
    review_draft,
)


EVIDENCE = Evidence(quote="Action: Publish the brief.", line_start=1, line_end=1)


def test_merge_keeps_teacher_summary_and_notes_but_human_entities() -> None:
    teacher = MeetingExtraction(
        title="Teacher title",
        summary="Teacher summary",
        notes=[
            MeetingNote(
                id="N1",
                title="Brief",
                description="The brief was assigned.",
                evidence=[EVIDENCE],
            )
        ],
        actions=[ActionItem(id="A1", task="Teacher action", evidence=[EVIDENCE])],
    )
    reference = MeetingExtraction(
        title="AMI meeting DEV001",
        summary="Reference summary",
        actions=[ActionItem(id="A1", task="Publish the brief", evidence=[EVIDENCE])],
    )

    merged = merge_human_annotations(teacher, reference)

    assert merged.title == reference.title
    assert merged.summary == teacher.summary
    assert merged.notes == teacher.notes
    assert merged.actions == reference.actions


def test_generation_is_resumable_and_marks_records_as_drafts(monkeypatch, tmp_path) -> None:
    extraction = MeetingExtraction(
        title="AMI meeting DEV001",
        summary="The brief was assigned.",
        notes=[
            MeetingNote(
                id="N1",
                title="Brief",
                description="The brief was assigned.",
                evidence=[EVIDENCE],
            )
        ],
    )
    calls = 0

    async def fake_extract_meeting(text, title, strategy, *, model=None):
        nonlocal calls
        calls += 1
        return extraction

    monkeypatch.setattr(sft_enrichment, "extract_meeting", fake_extract_meeting)
    case = {
        "id": "ami-dev001",
        "title": "AMI meeting DEV001",
        "transcript": "Action: Publish the brief.",
        "split": "development",
        "expected": MeetingExtraction(
            title="AMI meeting DEV001",
            summary="Human-annotated outcomes.",
            actions=[ActionItem(id="A1", task="Publish the brief", evidence=[EVIDENCE])],
        ).model_dump(mode="json"),
    }
    output = tmp_path / "drafts.json"

    first = asyncio.run(generate_enrichment_drafts([case], output, model="teacher"))
    second = asyncio.run(generate_enrichment_drafts([case], output, model="teacher"))

    assert calls == 1
    assert first == second
    assert first["ami-dev001"]["status"] == "draft"
    assert first["ami-dev001"]["generated_by"] == "teacher"
    assert first["ami-dev001"]["extraction"]["actions"][0]["task"] == "Publish the brief"


def test_review_requires_identity_and_grounded_output() -> None:
    drafts = {"ami-dev001": {"status": "draft"}}
    extraction = MeetingExtraction(
        title="Review",
        summary="The brief was assigned.",
        actions=[ActionItem(id="A1", task="Publish", evidence=[EVIDENCE])],
    )

    with pytest.raises(ValueError, match="Reviewer is required"):
        review_draft(drafts, "ami-dev001", extraction, EVIDENCE.quote, "", approved=True)

    invalid = extraction.model_copy(
        update={
            "actions": [
                ActionItem(
                    id="A1",
                    task="Invented",
                    evidence=[Evidence(quote="Invented quote", line_start=1, line_end=1)],
                )
            ]
        }
    )
    with pytest.raises(ValueError, match="Grounding validation failed"):
        review_draft(
            drafts,
            "ami-dev001",
            invalid,
            EVIDENCE.quote,
            "reviewer@example.com",
            approved=True,
        )


def test_review_records_approval_metadata() -> None:
    drafts = {"ami-dev001": {"status": "draft", "generated_by": "teacher"}}
    extraction = MeetingExtraction(
        title="Review",
        summary="The brief was assigned.",
        actions=[ActionItem(id="A1", task="Publish", evidence=[EVIDENCE])],
    )
    reviewed_at = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)

    record = review_draft(
        drafts,
        "ami-dev001",
        extraction,
        EVIDENCE.quote,
        "reviewer@example.com",
        approved=True,
        reviewed_at=reviewed_at,
    )

    assert record["status"] == "approved"
    assert record["reviewer"] == "reviewer@example.com"
    assert record["reviewed_at"] == "2026-09-27T12:00:00+00:00"
    assert record["generated_by"] == "teacher"