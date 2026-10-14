"""Build an evidence-linked chronology for one meeting."""

from meeting_to_action.advanced import TimelineEvent, TimelineKind, TranscriptSegment
from meeting_to_action.models import MeetingExtraction


def build_timeline(
    extraction: MeetingExtraction,
    segments: list[TranscriptSegment] | None = None,
) -> list[TimelineEvent]:
    speech_segments = segments or []
    records = [
        *((TimelineKind.ACTION, item, item.task) for item in extraction.actions),
        *((TimelineKind.DECISION, item, item.summary) for item in extraction.decisions),
        *((TimelineKind.QUESTION, item, item.question) for item in extraction.open_questions),
    ]
    events: list[TimelineEvent] = []
    for kind, record, label in records:
        evidence = record.evidence[0]
        segment = speech_segments[evidence.line_start - 1] if evidence.line_start <= len(speech_segments) else None
        events.append(TimelineEvent(
            id=f"{record.id}-timeline",
            kind=kind,
            label=label,
            detail=evidence.quote,
            start_ms=segment.start_ms if segment else None,
            end_ms=segment.end_ms if segment else None,
            speaker=segment.speaker if segment else None,
            record_id=record.id,
            line_start=evidence.line_start,
            line_end=evidence.line_end,
        ))
    return sorted(events, key=lambda event: (
        event.start_ms is None,
        event.start_ms if event.start_ms is not None else event.line_start or 0,
    ))