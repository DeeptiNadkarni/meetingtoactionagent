from pydantic import BaseModel

from meeting_to_action.models import ActionItem, Evidence, MeetingExtraction, MeetingNote
from meeting_to_action.review import apply_review_edits, build_change_audit


def test_review_edits_preserve_grounded_evidence() -> None:
    evidence = Evidence(quote="Maya will prepare the report.", line_start=1, line_end=1)
    extraction = MeetingExtraction(
        title="Weekly review",
        summary="Report work was assigned.",
        notes=[
            MeetingNote(
                id="N1",
                title="Report planning",
                description="The report was assigned.",
                evidence=[evidence],
            )
        ],
        actions=[ActionItem(id="A1", task="Prepare report", evidence=[evidence])],
    )

    reviewed = apply_review_edits(
        extraction,
        [{"id": "A1", "task": "Prepare final report", "owner": "Maya", "status": "confirmed"}],
        [],
        [],
        [{"id": "N1", "title": "Report next steps", "description": "Maya owns the report."}],
    )

    assert reviewed.actions[0].task == "Prepare final report"
    assert reviewed.actions[0].owner == "Maya"
    assert reviewed.actions[0].evidence == [evidence]
    assert reviewed.notes[0].title == "Report next steps"
    assert reviewed.notes[0].evidence == [evidence]


def test_review_edits_normalize_evidence_from_a_stale_model_class() -> None:
    class PreviousEvidence(BaseModel):
        quote: str
        line_start: int
        line_end: int

    stale_evidence = PreviousEvidence(
        quote="Maya will prepare the report.",
        line_start=1,
        line_end=1,
    )
    stale_action = ActionItem.model_construct(
        id="A1",
        task="Prepare report",
        evidence=[stale_evidence],
    )
    extraction = MeetingExtraction.model_construct(
        title="Weekly review",
        summary="Report work was assigned.",
        actions=[stale_action],
        decisions=[],
        open_questions=[],
        notes=[],
        warnings=[],
    )

    reviewed = apply_review_edits(
        extraction,
        [{"id": "A1", "task": "Prepare final report", "status": "confirmed"}],
        [],
        [],
    )

    assert reviewed.actions[0].evidence == [
        Evidence(quote="Maya will prepare the report.", line_start=1, line_end=1)
    ]


def test_change_audit_includes_only_edited_fields() -> None:
    evidence = Evidence(quote="Maya will prepare the report.", line_start=1, line_end=1)
    extraction = MeetingExtraction(
        title="Weekly review",
        summary="Report work was assigned.",
        notes=[
            MeetingNote(
                id="N1",
                title="Report planning",
                description="The report was assigned.",
                evidence=[evidence],
            )
        ],
        actions=[
            ActionItem(
                id="A1",
                task="Prepare report",
                owner=None,
                status="proposed",
                evidence=[evidence],
            )
        ],
    )
    reviewed = apply_review_edits(
        extraction,
        [
            {
                "id": "A1",
                "task": "Prepare final report",
                "owner": "Maya",
                "status": "confirmed",
            }
        ],
        [],
        [],
        [
            {
                "id": "N1",
                "title": "Report planning",
                "description": "The report was assigned.",
            }
        ],
    )

    assert build_change_audit(extraction, reviewed) == [
        {
            "record_type": "Action",
            "record_id": "A1",
            "field": "task",
            "before": "Prepare report",
            "after": "Prepare final report",
        },
        {
            "record_type": "Action",
            "record_id": "A1",
            "field": "owner",
            "before": None,
            "after": "Maya",
        },
        {
            "record_type": "Action",
            "record_id": "A1",
            "field": "status",
            "before": "proposed",
            "after": "confirmed",
        },
    ]