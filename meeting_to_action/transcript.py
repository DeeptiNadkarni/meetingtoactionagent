"""Transcript normalization and evidence-grounding checks."""

from dataclasses import dataclass
import re

from meeting_to_action.models import (
    ActionItem,
    Decision,
    Evidence,
    MeetingExtraction,
    MeetingNote,
    OpenQuestion,
)

TIMESTAMP_ONLY = re.compile(
    r"^\d+\s+minutes?(?:\s+\d+\s+seconds?)?\s*\d+:\d+$",
    re.IGNORECASE,
)
SPEAKER_TIMESTAMP = re.compile(
    r"^(?P<speaker>.+?)\s+\d+\s+minutes?(?:\s+\d+\s+seconds?)?$",
    re.IGNORECASE,
)


def _normalize_teams_export(raw_lines: list[str]) -> tuple[str, ...]:
    has_timestamp = any(TIMESTAMP_ONLY.match(line) for line in raw_lines)
    has_speaker_timestamp = any(SPEAKER_TIMESTAMP.match(line) for line in raw_lines)
    if not (has_timestamp and has_speaker_timestamp):
        return tuple(raw_lines)

    utterances: list[str] = []
    current_speaker: str | None = None
    index = 0
    while index < len(raw_lines):
        line = raw_lines[index]
        speaker_match = SPEAKER_TIMESTAMP.match(line)
        if speaker_match:
            current_speaker = speaker_match.group("speaker").strip()
        elif TIMESTAMP_ONLY.match(line):
            pass
        elif index + 1 < len(raw_lines) and TIMESTAMP_ONLY.match(raw_lines[index + 1]):
            current_speaker = line
        else:
            utterances.append(f"{current_speaker}: {line}" if current_speaker else line)
        index += 1
    return tuple(utterances)


@dataclass(frozen=True)
class NumberedTranscript:
    lines: tuple[str, ...]

    @classmethod
    def from_text(cls, text: str) -> "NumberedTranscript":
        raw_lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not raw_lines:
            raise ValueError("Transcript must contain at least one non-empty line")
        return cls(lines=_normalize_teams_export(raw_lines))

    def prompt_text(self) -> str:
        return "\n".join(f"{index}: {line}" for index, line in enumerate(self.lines, 1))

    def contains(self, evidence: Evidence) -> bool:
        if evidence.line_end > len(self.lines):
            return False
        source = "\n".join(self.lines[evidence.line_start - 1 : evidence.line_end])
        return evidence.quote.strip() in source

    def locate_exact_quote(self, quote: str, max_lines: int = 5) -> tuple[int, int] | None:
        stripped_quote = quote.strip()
        single_line_matches = [
            (index, index)
            for index, line in enumerate(self.lines, 1)
            if stripped_quote in line
        ]
        if len(single_line_matches) == 1:
            return single_line_matches[0]
        if single_line_matches:
            return None

        matches: list[tuple[int, int]] = []
        for start in range(len(self.lines)):
            for end in range(start + 1, min(start + max_lines, len(self.lines))):
                selected = self.lines[start : end + 1]
                if stripped_quote in "\n".join(selected) or stripped_quote in " ".join(selected):
                    matches.append((start + 1, end + 1))
                    break
        shortest_span = min((end - start for start, end in matches), default=None)
        shortest = [match for match in matches if match[1] - match[0] == shortest_span]
        return shortest[0] if len(shortest) == 1 else None


def repair_grounding(
    extraction: MeetingExtraction,
    transcript: NumberedTranscript,
) -> MeetingExtraction:
    warnings: list[str] = []

    def repair_record(record: ActionItem | Decision | MeetingNote | OpenQuestion):
        repaired_evidence: list[Evidence] = []
        for evidence in record.evidence:
            if transcript.contains(evidence):
                repaired_evidence.append(evidence)
                continue
            located = transcript.locate_exact_quote(evidence.quote)
            if located:
                repaired_evidence.append(
                    evidence.model_copy(update={"line_start": located[0], "line_end": located[1]})
                )
                warnings.append(f"{record.id}: corrected evidence line range")
            else:
                warnings.append(f"{record.id}: removed unsupported evidence quote")
        if not repaired_evidence:
            warnings.append(f"{record.id}: omitted because it has no exact transcript evidence")
            return None

        updates: dict[str, object] = {"evidence": repaired_evidence}
        if isinstance(record, ActionItem):
            cited_text = "\n".join(evidence.quote for evidence in repaired_evidence)
            if record.deadline_text and record.deadline_text.lower() not in cited_text.lower():
                updates.update(deadline_text=None, deadline=None)
                warnings.append(f"{record.id}: removed a deadline not present in its evidence")
            elif record.deadline and str(record.deadline.year) not in cited_text:
                updates["deadline"] = None
                warnings.append(f"{record.id}: kept deadline text but removed an inferred year")
        return record.model_copy(update=updates)

    notes = [item for record in extraction.notes if (item := repair_record(record))]
    actions = [item for record in extraction.actions if (item := repair_record(record))]
    decisions = [item for record in extraction.decisions if (item := repair_record(record))]
    questions = [item for record in extraction.open_questions if (item := repair_record(record))]
    return extraction.model_copy(
        update={
            "notes": notes,
            "actions": actions,
            "decisions": decisions,
            "open_questions": questions,
            "warnings": warnings,
        }
    )


def validate_grounding(
    extraction: MeetingExtraction,
    transcript: NumberedTranscript,
) -> list[str]:
    errors: list[str] = []
    records = [
        *extraction.notes,
        *extraction.actions,
        *extraction.decisions,
        *extraction.open_questions,
    ]
    for record in records:
        for evidence in record.evidence:
            if not transcript.contains(evidence):
                errors.append(
                    f"{record.id}: quote is not present in lines "
                    f"{evidence.line_start}-{evidence.line_end}"
                )
        if hasattr(record, "deadline_text"):
            cited_text = "\n".join(evidence.quote for evidence in record.evidence)
            if record.deadline_text and record.deadline_text.lower() not in cited_text.lower():
                errors.append(f"{record.id}: deadline text is not present in its evidence")
            if record.deadline and str(record.deadline.year) not in cited_text:
                errors.append(f"{record.id}: normalized deadline year is not explicit in its evidence")
    return errors