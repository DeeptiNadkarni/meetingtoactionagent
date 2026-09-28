"""Extraction strategies backed by Microsoft Agent Framework and Foundry."""

import asyncio
import os
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import date
from enum import StrEnum
from typing import TypeVar

from pydantic import BaseModel, Field

from meeting_to_action.models import ActionItem, Decision, MeetingExtraction, MeetingNote, OpenQuestion
from meeting_to_action.transcript import NumberedTranscript, repair_grounding, validate_grounding

PROJECT_ENDPOINT_ENV = "FOUNDRY_PROJECT_ENDPOINT"
MODEL_ENV = "FOUNDRY_MODEL"
TRAINED_MODEL_ENV = "FOUNDRY_TRAINED_MODEL"
DEFAULT_MODEL = "gpt-5.4-mini"
MANAGED_IDENTITY_ENV = "AZURE_USE_MANAGED_IDENTITY"


class ExtractionStrategy(StrEnum):
    SINGLE = "Single model"
    VERIFIED = "Extractor + verifier"
    SPECIALISTS = "Specialists + consolidator"
    DEMO = "Rule-based demo (no AI)"


class ActionList(BaseModel):
    actions: list[ActionItem] = Field(default_factory=list)


class DecisionList(BaseModel):
    decisions: list[Decision] = Field(default_factory=list)


class QuestionList(BaseModel):
    open_questions: list[OpenQuestion] = Field(default_factory=list)


T = TypeVar("T", bound=BaseModel)


def _demo_note_topic(text: str) -> str:
    lowered = text.lower()
    topic_rules = (
        (("legal", "approval"), "Legal Approval"),
        (("flight", "hotel", "booking", "reservation"), "Travel Booking"),
        (("travel", "trip", "itinerary"), "Travel Planning"),
        (("logistics", "transport", "venue", "shipping"), "Logistics Coordination"),
        (("budget", "cost", "pricing", "expense"), "Budget and Costs"),
        (("launch brief", "readiness", "checklist"), "Launch Readiness"),
        (("customer", "participant", "attendee", "invitee"), "Participants and Invitations"),
        (("region", "rollout"), "Pilot Rollout"),
        (("launch date", "launch the pilot on", "schedule", "timeline"), "Pilot Timeline"),
    )
    for keywords, title in topic_rules:
        if any(keyword in lowered for keyword in keywords):
            return title
    return "Meeting Context"


def foundry_is_configured() -> bool:
    return bool(os.getenv(PROJECT_ENDPOINT_ENV))


def _create_azure_credential():
    from azure.identity.aio import AzureCliCredential, ManagedIdentityCredential

    if os.getenv(MANAGED_IDENTITY_ENV, "").lower() == "true":
        return ManagedIdentityCredential()
    return AzureCliCredential()


@asynccontextmanager
async def _create_agent(name: str, instructions: str, model: str | None = None):
    from agent_framework import Agent
    from agent_framework.foundry import FoundryChatClient

    credential = _create_azure_credential()
    client = FoundryChatClient(
        project_endpoint=os.environ[PROJECT_ENDPOINT_ENV],
        model=model or os.getenv(MODEL_ENV, DEFAULT_MODEL),
        credential=credential,
    )
    agent = Agent(client=client, name=name, instructions=instructions)
    async with AsyncExitStack() as stack:
        stack.push_async_callback(credential.close)
        stack.push_async_callback(client.project_client.close)
        stack.push_async_callback(client.client.close)
        await stack.enter_async_context(agent)
        yield agent


async def _run_structured(
    name: str,
    instructions: str,
    prompt: str,
    output_type: type[T],
    model: str | None = None,
) -> T:
    async with _create_agent(name, instructions, model=model) as agent:
        response = await agent.run(prompt, options={"response_format": output_type})
    if not isinstance(response.value, output_type):
        raise RuntimeError(f"{name} did not return valid structured output")
    return response.value


GROUNDING_RULES = """
Use only facts explicitly stated in the numbered transcript. Every record must include at
least one verbatim quote and its exact 1-based line range. Never infer an owner or deadline.
Copy any deadline phrase verbatim into deadline_text. Set the normalized deadline date only
when its year is explicitly stated; relative dates such as Friday must have deadline=null.
Use null when a value is not explicit. Keep action items, decisions, and unresolved questions
distinct. Group related meeting events into concise topical note sections. Derive each section
title from the actual subject discussed, such as Travel planning, Booking, or Logistics; never
use generic buckets such as Discussion, Decisions, Actions, Next steps, or Open questions.
Write titles as semantically specific, properly capitalized noun phrases rather than clipped
keywords or sentence fragments. Write each description as one to three brief, complete,
grammatically correct sentences explaining what happened. Include supporting evidence and
cover substantive discussion as well as outcomes without unnecessary repetition. Return no
record when the transcript provides no supporting quote.
""".strip()


async def extract_single(
    transcript: NumberedTranscript,
    title: str,
    model: str | None = None,
) -> MeetingExtraction:
    prompt = f"Meeting title: {title}\n\nNumbered transcript:\n{transcript.prompt_text()}"
    return await _run_structured(
        "MeetingExtractor",
        f"Extract a complete meeting record. {GROUNDING_RULES}",
        prompt,
        MeetingExtraction,
        model=model,
    )


async def extract_verified(
    transcript: NumberedTranscript,
    title: str,
    model: str | None = None,
) -> MeetingExtraction:
    draft = await extract_single(transcript, title, model=model)
    prompt = (
        f"Numbered transcript:\n{transcript.prompt_text()}\n\n"
        f"Draft extraction:\n{draft.model_dump_json(indent=2)}"
    )
    return await _run_structured(
        "MeetingVerifier",
        "Audit the draft against the transcript. Remove unsupported records, correct exact quotes "
        f"and line ranges, and return the corrected complete record. {GROUNDING_RULES}",
        prompt,
        MeetingExtraction,
        model=model,
    )


async def extract_specialists(
    transcript: NumberedTranscript,
    title: str,
    model: str | None = None,
) -> MeetingExtraction:
    source = f"Meeting title: {title}\n\nNumbered transcript:\n{transcript.prompt_text()}"
    actions_task = _run_structured(
        "ActionSpecialist",
        f"Extract only action items. {GROUNDING_RULES}",
        source,
        ActionList,
        model=model,
    )
    decisions_task = _run_structured(
        "DecisionSpecialist",
        f"Extract only decisions. {GROUNDING_RULES}",
        source,
        DecisionList,
        model=model,
    )
    questions_task = _run_structured(
        "QuestionSpecialist",
        f"Extract only unresolved questions. {GROUNDING_RULES}",
        source,
        QuestionList,
        model=model,
    )
    actions, decisions, questions = await asyncio.gather(
        actions_task,
        decisions_task,
        questions_task,
    )
    candidates = MeetingExtraction(
        title=title,
        summary="Pending consolidation",
        actions=actions.actions,
        decisions=decisions.decisions,
        open_questions=questions.open_questions,
    )
    prompt = (
        f"Numbered transcript:\n{transcript.prompt_text()}\n\n"
        f"Specialist candidates:\n{candidates.model_dump_json(indent=2)}"
    )
    return await _run_structured(
        "MeetingConsolidator",
        "Deduplicate and verify specialist candidates, write a concise meeting summary and "
        f"structured meeting notes, then return one complete record. {GROUNDING_RULES}",
        prompt,
        MeetingExtraction,
        model=model,
    )


def extract_demo(transcript: NumberedTranscript, title: str) -> MeetingExtraction:
    actions: list[ActionItem] = []
    decisions: list[Decision] = []
    questions: list[OpenQuestion] = []
    note_groups: dict[str, dict[str, list[object]]] = {}
    for line_number, line in enumerate(transcript.lines, 1):
        lowered = line.lower()
        evidence = [{"quote": line, "line_start": line_number, "line_end": line_number}]
        description = line.split(":", 1)[-1].strip()
        topic = _demo_note_topic(description)
        group = note_groups.setdefault(topic, {"descriptions": [], "evidence": []})
        group["descriptions"].append(description)
        group["evidence"].extend(evidence)
        if "action:" in lowered:
            actions.append(
                ActionItem(
                    id=f"A{len(actions) + 1}",
                    task=line.split(":", 1)[1].strip(),
                    evidence=evidence,
                )
            )
        elif "decision:" in lowered:
            decisions.append(
                Decision(
                    id=f"D{len(decisions) + 1}",
                    summary=line.split(":", 1)[1].strip(),
                    evidence=evidence,
                )
            )
        elif "open question:" in lowered:
            questions.append(
                OpenQuestion(
                    id=f"Q{len(questions) + 1}",
                    question=line.split(":", 1)[1].strip(),
                    evidence=evidence,
                )
            )
    notes = [
        MeetingNote(
            id=f"N{index}",
            title=topic,
            description=" ".join(str(item) for item in group["descriptions"]),
            evidence=group["evidence"],
        )
        for index, (topic, group) in enumerate(note_groups.items(), 1)
    ]
    return MeetingExtraction(
        title=title,
        meeting_date=date.today(),
        summary=(
            f"Captured {len(actions)} actions, {len(decisions)} decisions, and "
            f"{len(questions)} open questions."
        ),
        notes=notes,
        actions=actions,
        decisions=decisions,
        open_questions=questions,
    )


async def extract_meeting(
    text: str,
    title: str,
    strategy: ExtractionStrategy,
    *,
    model: str | None = None,
) -> MeetingExtraction:
    transcript = NumberedTranscript.from_text(text)
    handlers: dict[
        ExtractionStrategy,
        Callable[[NumberedTranscript, str, str | None], Awaitable[MeetingExtraction]],
    ] = {
        ExtractionStrategy.SINGLE: extract_single,
        ExtractionStrategy.VERIFIED: extract_verified,
        ExtractionStrategy.SPECIALISTS: extract_specialists,
    }
    if strategy is ExtractionStrategy.DEMO:
        result = extract_demo(transcript, title)
    else:
        if not foundry_is_configured():
            raise RuntimeError(f"{PROJECT_ENDPOINT_ENV} is required for {strategy.value}")
        result = await handlers[strategy](transcript, title, model)
    result = repair_grounding(result, transcript)
    grounding_errors = validate_grounding(result, transcript)
    if grounding_errors:
        raise RuntimeError("Grounding validation failed: " + "; ".join(grounding_errors))
    return result