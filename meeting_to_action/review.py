"""Human review transformations that preserve model-supplied evidence."""

from collections.abc import Mapping, Sequence
from typing import Any

from meeting_to_action.models import ActionItem, Decision, MeetingExtraction, MeetingNote, OpenQuestion


AUDITED_FIELDS = (
    ("Meeting note", "notes", ("title", "description")),
    ("Action", "actions", ("task", "owner", "deadline_text", "deadline", "status")),
    ("Decision", "decisions", ("summary", "rationale")),
    ("Open question", "open_questions", ("question", "owner")),
)


def _evidence_payload(items: Sequence[Any]) -> list[dict[str, Any]]:
    return [item.model_dump(mode="python") for item in items]


def build_change_audit(
    extraction: MeetingExtraction,
    reviewed: MeetingExtraction,
) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for record_type, collection_name, fields in AUDITED_FIELDS:
        original_by_id = {item.id: item for item in getattr(extraction, collection_name)}
        for approved in getattr(reviewed, collection_name):
            original = original_by_id.get(approved.id)
            if original is None:
                continue
            for field in fields:
                before = getattr(original, field)
                after = getattr(approved, field)
                if before != after:
                    changes.append(
                        {
                            "record_type": record_type,
                            "record_id": approved.id,
                            "field": field,
                            "before": before,
                            "after": after,
                        }
                    )
    return changes


def apply_review_edits(
    extraction: MeetingExtraction,
    action_rows: Sequence[Mapping[str, Any]],
    decision_rows: Sequence[Mapping[str, Any]],
    question_rows: Sequence[Mapping[str, Any]],
    note_rows: Sequence[Mapping[str, Any]] | None = None,
) -> MeetingExtraction:
    actions_by_id = {item.id: item for item in extraction.actions}
    decisions_by_id = {item.id: item for item in extraction.decisions}
    questions_by_id = {item.id: item for item in extraction.open_questions}
    notes_by_id = {item.id: item for item in extraction.notes}

    actions = [
        ActionItem(
            **row,
            evidence=_evidence_payload(actions_by_id[str(row["id"])].evidence),
        )
        for row in action_rows
    ]
    decisions = [
        Decision(
            **row,
            evidence=_evidence_payload(decisions_by_id[str(row["id"])].evidence),
        )
        for row in decision_rows
    ]
    questions = [
        OpenQuestion(
            **row,
            evidence=_evidence_payload(questions_by_id[str(row["id"])].evidence),
        )
        for row in question_rows
    ]
    notes = extraction.notes if note_rows is None else [
        MeetingNote(
            **row,
            evidence=_evidence_payload(notes_by_id[str(row["id"])].evidence),
        )
        for row in note_rows
    ]
    return extraction.model_copy(
        update={
            "notes": notes,
            "actions": actions,
            "decisions": decisions,
            "open_questions": questions,
        }
    )