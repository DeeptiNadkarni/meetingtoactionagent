from datetime import date

import pytest
from pydantic import ValidationError

from meeting_to_action.models import ActionItem, Evidence, MeetingExtraction, MeetingNote


def test_meeting_extraction_accepts_grounded_action() -> None:
    extraction = MeetingExtraction(
        title="Launch review",
        meeting_date=date(2026, 9, 22),
        summary="The team assigned launch preparation.",
        actions=[
            ActionItem(
                id="A1",
                task="Prepare the launch checklist",
                owner="Maya",
                deadline=date(2026, 9, 25),
                evidence=[
                    Evidence(
                        quote="Maya, please prepare the launch checklist by Friday.",
                        line_start=8,
                        line_end=8,
                    )
                ],
            )
        ],
    )

    assert extraction.actions[0].owner == "Maya"
    assert extraction.actions[0].evidence[0].line_start == 8


def test_evidence_rejects_reversed_line_range() -> None:
    with pytest.raises(ValidationError, match="line_end"):
        Evidence(quote="Exact transcript quote", line_start=9, line_end=8)


def test_action_requires_evidence() -> None:
    with pytest.raises(ValidationError):
        ActionItem(id="A1", task="Prepare the launch checklist", evidence=[])


def test_meeting_notes_are_structured_and_grounded() -> None:
    evidence = Evidence(quote="The team reviewed the launch plan.", line_start=2, line_end=2)
    extraction = MeetingExtraction(
        title="Launch review",
        summary="The launch plan was reviewed.",
        notes=[
            MeetingNote(
                id="N1",
                title="Launch plan",
                description="The team reviewed the plan and discussed readiness.",
                evidence=[evidence],
            )
        ],
    )

    assert extraction.notes[0].title == "Launch plan"
    assert extraction.notes[0].evidence == [evidence]

    with pytest.raises(ValidationError):
        MeetingNote(id="N2", title="Next steps", description="Follow-up work", evidence=[])