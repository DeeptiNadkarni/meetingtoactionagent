"""Grounded question answering over a meeting transcript."""

from pydantic import BaseModel, Field, model_validator

from meeting_to_action.extraction import GROUNDING_RULES, _run_structured
from meeting_to_action.models import Evidence, MeetingExtraction
from meeting_to_action.retrieval import retrieve_transcript
from meeting_to_action.transcript import NumberedTranscript


class GroundedAnswer(BaseModel):
    answer: str = Field(min_length=1)
    supported: bool
    citations: list[Evidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def supported_answers_require_citations(self) -> "GroundedAnswer":
        if self.supported and not self.citations:
            raise ValueError("Supported answers require at least one citation")
        return self


def validate_answer(answer: GroundedAnswer, transcript: NumberedTranscript) -> list[str]:
    return [
        f"Citation {index} is not present in its declared line range"
        for index, citation in enumerate(answer.citations, 1)
        if not transcript.contains(citation)
    ]


async def answer_question(
    question: str,
    transcript: NumberedTranscript,
    extraction: MeetingExtraction,
) -> GroundedAnswer:
    retrieved = retrieve_transcript(transcript, question)
    prompt = (
        f"Retrieved transcript evidence:\n{retrieved.prompt_text()}\n\n"
        f"Reviewed meeting record:\n{extraction.model_dump_json(indent=2)}\n\n"
        f"Question: {question}"
    )
    answer = await _run_structured(
        "MeetingAssistant",
        "Use the transcript and reviewed meeting record as the only factual sources. Answer "
        "direct factual questions from explicit statements. For analytical, improvement, or "
        "recommendation questions, synthesize useful suggestions from meeting evidence and "
        "clearly label them as recommendations or analysis, not as decisions made in the meeting. "
        "Set supported=true and cite the exact evidence that supports each fact or recommendation. "
        "Do not add outside facts, invent details, or infer an unstated owner or deadline. If the "
        "topic has no relevant meeting evidence, set supported=false, use no citations, and explain "
        f"that the meeting did not cover it. {GROUNDING_RULES}",
        prompt,
        GroundedAnswer,
    )
    errors = validate_answer(answer, transcript)
    if errors:
        raise RuntimeError("Grounding validation failed: " + "; ".join(errors))
    return answer