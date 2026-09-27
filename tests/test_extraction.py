import asyncio
from datetime import date

import pytest
from azure.identity.aio import AzureCliCredential, ManagedIdentityCredential

import meeting_to_action.extraction as extraction_module
from meeting_to_action.extraction import (
    MANAGED_IDENTITY_ENV,
    ExtractionStrategy,
    _create_azure_credential,
    extract_meeting,
)
from meeting_to_action.models import ActionItem, Evidence, MeetingExtraction
from meeting_to_action.transcript import NumberedTranscript, repair_grounding, validate_grounding


TRANSCRIPT = """Facilitator: We need to settle the launch date.
Decision: Launch the pilot on October 15.
Action: Prepare the customer readiness checklist.
Open question: Which three customers should join the pilot?
"""


@pytest.mark.parametrize(
    ("environment_value", "credential_type"),
    [(None, AzureCliCredential), ("true", ManagedIdentityCredential), ("TRUE", ManagedIdentityCredential)],
)
def test_azure_credential_matches_runtime_environment(
    monkeypatch: pytest.MonkeyPatch,
    environment_value: str | None,
    credential_type: type,
) -> None:
    if environment_value is None:
        monkeypatch.delenv(MANAGED_IDENTITY_ENV, raising=False)
    else:
        monkeypatch.setenv(MANAGED_IDENTITY_ENV, environment_value)

    credential = _create_azure_credential()

    assert isinstance(credential, credential_type)
    asyncio.run(credential.close())


def test_structured_run_closes_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    extraction = MeetingExtraction(title="Test", summary="Complete")

    class FakeAgent:
        closed = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_value, traceback):
            self.closed = True

        async def run(self, prompt, options):
            return type("Response", (), {"value": extraction})()

    agent = FakeAgent()
    monkeypatch.setattr(extraction_module, "_create_agent", lambda *args, **kwargs: agent)

    result = asyncio.run(
        extraction_module._run_structured("TestAgent", "Instructions", "Prompt", MeetingExtraction)
    )

    assert result is extraction
    assert agent.closed


def test_numbered_transcript_checks_exact_quote_and_range() -> None:
    transcript = NumberedTranscript.from_text(TRANSCRIPT)

    assert transcript.contains(
        Evidence(
            quote="Launch the pilot on October 15.",
            line_start=2,
            line_end=2,
        )
    )
    assert not transcript.contains(
        Evidence(quote="Launch in November.", line_start=2, line_end=2)
    )


def test_demo_strategy_extracts_explicit_markers() -> None:
    result = asyncio.run(
        extract_meeting(TRANSCRIPT, "Pilot planning", ExtractionStrategy.DEMO)
    )

    assert len(result.actions) == 1
    assert len(result.decisions) == 1
    assert len(result.open_questions) == 1
    assert len(result.notes) == 3
    assert not {note.title for note in result.notes} & {
        "Discussion",
        "Decisions",
        "Actions",
        "Next steps",
        "Open questions",
    }
    assert [note.title for note in result.notes] == [
        "Pilot Timeline",
        "Launch Readiness",
        "Participants and Invitations",
    ]
    assert all(note.description for note in result.notes)
    assert all(note.title.lower() != note.description.rstrip(".?!").lower() for note in result.notes)
    assert result.decisions[0].evidence[0].line_start == 2


def test_demo_notes_group_related_events_under_semantic_topics() -> None:
    transcript = """Maya: The launch brief must be ready before the review.
Action: Maya will prepare the launch brief by Friday.
Open question: Do we need legal approval for the invitation?
Jon: I will ask legal and report back."""

    result = asyncio.run(
        extract_meeting(transcript, "Launch review", ExtractionStrategy.DEMO)
    )

    assert [note.title for note in result.notes] == ["Launch Readiness", "Legal Approval"]
    assert len(result.notes[0].evidence) == 2
    assert len(result.notes[1].evidence) == 2


def test_empty_transcript_is_rejected() -> None:
    with pytest.raises(ValueError, match="Transcript"):
        asyncio.run(extract_meeting("\n", "Empty", ExtractionStrategy.DEMO))


def test_relative_deadline_cannot_be_normalized_without_explicit_year() -> None:
    transcript = NumberedTranscript.from_text("Action: Maya will publish the brief Friday.")
    extraction = MeetingExtraction(
        title="Launch",
        summary="A brief was assigned.",
        actions=[
            ActionItem(
                id="A1",
                task="Publish the brief",
                owner="Maya",
                deadline_text="Friday",
                deadline=date(2026, 9, 25),
                evidence=[Evidence(quote=transcript.lines[0], line_start=1, line_end=1)],
            )
        ],
    )

    assert "normalized deadline year is not explicit" in validate_grounding(extraction, transcript)[0]


def test_teams_export_is_normalized_to_speaker_turns() -> None:
    transcript = NumberedTranscript.from_text(
        """Maya Singh
0 minutes 43 seconds0:43
Maya Singh 0 minutes 43 seconds
We need the launch brief.
Alex Chen 1 minute 2 seconds
I will prepare it Friday."""
    )

    assert transcript.lines == (
        "Maya Singh: We need the launch brief.",
        "Alex Chen: I will prepare it Friday.",
    )


def test_grounding_repair_corrects_range_and_removes_invalid_deadline() -> None:
    transcript = NumberedTranscript.from_text(
        "Maya: We need a brief.\nAlex: I will prepare it Friday."
    )
    extraction = MeetingExtraction(
        title="Launch",
        summary="A brief was assigned.",
        actions=[
            ActionItem(
                id="A1",
                task="Prepare the brief",
                owner="Alex",
                deadline_text="next Friday",
                evidence=[
                    Evidence(
                        quote="Alex: I will prepare it Friday.",
                        line_start=1,
                        line_end=1,
                    )
                ],
            )
        ],
    )

    repaired = repair_grounding(extraction, transcript)

    assert repaired.actions[0].evidence[0].line_start == 2
    assert repaired.actions[0].deadline_text is None
    assert len(repaired.warnings) == 2


def test_grounding_repair_omits_record_without_exact_quote() -> None:
    transcript = NumberedTranscript.from_text("Maya: We need a brief.")
    extraction = MeetingExtraction(
        title="Launch",
        summary="No supported action.",
        actions=[
            ActionItem(
                id="A1",
                task="Publish the brief",
                evidence=[Evidence(quote="Alex will publish it.", line_start=1, line_end=1)],
            )
        ],
    )

    repaired = repair_grounding(extraction, transcript)

    assert repaired.actions == []
    assert repaired.warnings[-1].endswith("no exact transcript evidence")


def test_exact_quote_substring_can_repair_line_range() -> None:
    transcript = NumberedTranscript.from_text(
        "Maya: Intro.\nAlex: I will prepare the final launch brief by Friday."
    )

    assert transcript.locate_exact_quote("prepare the final launch brief") == (2, 2)