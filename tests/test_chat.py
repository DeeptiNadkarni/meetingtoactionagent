import asyncio

import pytest
from pydantic import ValidationError

from meeting_to_action import chat
from meeting_to_action.chat import GroundedAnswer, answer_question, validate_answer
from meeting_to_action.models import MeetingExtraction
from meeting_to_action.retrieval import retrieve_transcript
from meeting_to_action.transcript import NumberedTranscript


def test_supported_answer_requires_citation() -> None:
    with pytest.raises(ValidationError):
        GroundedAnswer(answer="Alex owns it.", supported=True)


def test_answer_citations_are_checked_against_transcript() -> None:
    transcript = NumberedTranscript.from_text("Alex will publish the report Friday.")
    answer = GroundedAnswer(
        answer="Alex owns the report.",
        supported=True,
        citations=[{"quote": "Alex owns the report", "line_start": 1, "line_end": 1}],
    )

    assert validate_answer(answer, transcript)


def test_retrieval_ranks_relevant_lines_and_keeps_neighboring_context() -> None:
    transcript = NumberedTranscript.from_text(
        "Maya opened the meeting.\n"
        "The launch date remains unchanged.\n"
        "Alex owns the customer brief.\n"
        "The brief is due Friday.\n"
        "The team discussed office catering."
    )

    result = retrieve_transcript(
        transcript,
        "Who owns the customer brief?",
        top_k=1,
        neighbor_lines=1,
    )

    assert result.line_numbers == (2, 3, 4)
    assert "3: Alex owns the customer brief." in result.prompt_text()
    assert "office catering" not in result.prompt_text()


def test_analytical_questions_request_grounded_recommendations(monkeypatch) -> None:
    transcript = NumberedTranscript.from_text(
        "The approval process was lengthy and confusing for users."
    )
    extraction = MeetingExtraction(
        title="Guest sponsorship",
        summary="The team discussed the guest sponsorship workflow.",
    )
    captured: dict[str, str] = {}

    async def fake_run_structured(name, instructions, prompt, response_format):
        captured["instructions"] = instructions
        captured["prompt"] = prompt
        return GroundedAnswer(
            answer=(
                "Recommendation: simplify the sponsorship workflow because users described the "
                "approval process as lengthy and confusing."
            ),
            supported=True,
            citations=[
                {
                    "quote": "The approval process was lengthy and confusing for users.",
                    "line_start": 1,
                    "line_end": 1,
                }
            ],
        )

    monkeypatch.setattr(chat, "_run_structured", fake_run_structured)

    answer = asyncio.run(
        answer_question(
            "What improvements would you suggest?",
            transcript,
            extraction,
        )
    )

    assert answer.supported
    assert answer.citations
    assert "Retrieved transcript evidence" in captured["prompt"]
    assert "synthesize useful suggestions" in captured["instructions"]
    assert "not as decisions made in the meeting" in captured["instructions"]