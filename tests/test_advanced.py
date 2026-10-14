from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from meeting_to_action.advanced import (
    CorrectionEvent,
    ContextDocument,
    QualityFinding,
    QualitySeverity,
    TimelineEvent,
    TimelineKind,
    TranscriptSegment,
)
from meeting_to_action.models import ActionItem, Evidence, MeetingExtraction
from meeting_to_action.quality import analyze_quality
from meeting_to_action.speech import segments_from_document, transcribe_media
from meeting_to_action.timeline import build_timeline


def test_transcript_segment_requires_forward_timestamp_range() -> None:
    segment = TranscriptSegment(
        id="S1",
        text="Maya will prepare the launch brief.",
        start_ms=1_250,
        end_ms=3_700,
        speaker="Maya",
        confidence=0.91,
    )

    assert segment.speaker == "Maya"
    with pytest.raises(ValidationError, match="end_ms"):
        TranscriptSegment(id="S2", text="Invalid", start_ms=4_000, end_ms=4_000)


def test_quality_finding_explains_reason_without_score() -> None:
    finding = QualityFinding(
        code="missing-owner",
        severity=QualitySeverity.REVIEW,
        title="Action owner needs review",
        detail="Action A1 has no owner stated in its transcript evidence.",
        record_ids=["A1"],
        line_numbers=[8],
    )

    assert finding.model_dump()["severity"] == QualitySeverity.REVIEW
    assert "score" not in finding.model_dump()


def test_correction_and_timeline_records_remain_auditable() -> None:
    changed_at = datetime(2026, 4, 1, 15, 30, tzinfo=UTC)
    correction = CorrectionEvent(
        changed_at=changed_at,
        actor="Reviewer",
        record_type="Action",
        record_id="A1",
        field="owner",
        before=None,
        after="Maya",
    )
    event = TimelineEvent(
        id="A1-1",
        kind=TimelineKind.ACTION,
        label="Action assigned",
        detail="Maya will prepare the launch brief.",
        start_ms=1_250,
        end_ms=3_700,
        speaker="Maya",
        record_id="A1",
        line_start=8,
        line_end=8,
    )

    assert correction.changed_at == changed_at
    assert event.record_id == "A1"


def test_speech_result_becomes_speaker_timestamped_transcript() -> None:
    phrase = SimpleNamespace(
        text="Maya will prepare the launch brief.",
        offset_milliseconds=1_250,
        duration_milliseconds=2_450,
        speaker=1,
        locale="en-US",
    )
    client = SimpleNamespace(transcribe=lambda content: SimpleNamespace(phrases=[phrase]))

    document = transcribe_media("meeting.wav", b"RIFF-test-audio", client=client)
    segments = segments_from_document(document)

    assert document.text == "Speaker 1: Maya will prepare the launch brief."
    assert segments[0].start_ms == 1_250
    assert segments[0].end_ms == 3_700


def test_quality_analysis_explains_conflict_and_context_alignment() -> None:
    evidence = Evidence(quote="Prepare the launch brief.", line_start=2, line_end=2)
    extraction = MeetingExtraction(
        title="Launch review",
        summary="The team assigned launch work.",
        actions=[
            ActionItem(
                id="A1",
                task="Prepare the launch brief",
                owner="Maya",
                deadline_text="Friday",
                evidence=[evidence],
            ),
            ActionItem(
                id="A2",
                task="Prepare launch brief",
                owner="Jon",
                deadline_text="Monday",
                evidence=[evidence],
            ),
        ],
    )
    context = ContextDocument(
        id="agenda-1",
        title="Agenda",
        filename="agenda.txt",
        text="Confirm who will prepare the launch brief",
        content_hash="abc123",
    )

    findings = analyze_quality(extraction, [context])

    assert any(finding.code == "action-conflict" for finding in findings)
    assert any(finding.context_citations for finding in findings)


def test_timeline_maps_evidence_line_to_speech_segment() -> None:
    extraction = MeetingExtraction(
        title="Launch review",
        summary="The launch brief was assigned.",
        actions=[ActionItem(
            id="A1",
            task="Prepare the launch brief",
            evidence=[Evidence(quote="Prepare the launch brief.", line_start=2, line_end=2)],
        )],
    )
    segments = [
        TranscriptSegment(id="S1", text="Opening", start_ms=0, end_ms=1_000),
        TranscriptSegment(
            id="S2",
            text="Prepare the launch brief.",
            start_ms=1_250,
            end_ms=3_700,
            speaker="Speaker 1",
        ),
    ]

    timeline = build_timeline(extraction, segments)

    assert timeline[0].start_ms == 1_250
    assert timeline[0].speaker == "Speaker 1"