"""Evaluation runner for extraction architecture comparisons."""

import argparse
import asyncio
import json
import os
import time
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from meeting_to_action.extraction import ExtractionStrategy, _run_structured, extract_meeting
from meeting_to_action.models import MeetingExtraction
from meeting_to_action.transcript import NumberedTranscript, validate_grounding

MODEL_CALLS = {
    ExtractionStrategy.SINGLE: 1,
    ExtractionStrategy.VERIFIED: 2,
    ExtractionStrategy.SPECIALISTS: 4,
}
JUDGE_MODEL_ENV = "FOUNDRY_JUDGE_MODEL"


class JudgeScores(BaseModel):
    correctness: int = Field(ge=1, le=5)
    completeness: int = Field(ge=1, le=5)
    grounding: int = Field(ge=1, le=5)
    rationale: str = Field(min_length=1)


def judge_model_name() -> str:
    judge_model = os.getenv(JUDGE_MODEL_ENV, "").strip()
    generation_model = os.getenv("FOUNDRY_MODEL", "gpt-5.4-mini").strip()
    if not judge_model:
        raise RuntimeError(
            f"{JUDGE_MODEL_ENV} must name a separate deployed Foundry model before judged evaluation"
        )
    if judge_model.casefold() == generation_model.casefold():
        raise RuntimeError(f"{JUDGE_MODEL_ENV} must differ from FOUNDRY_MODEL")
    return judge_model


def entity_keys(extraction: MeetingExtraction) -> set[str]:
    return {
        *(f"action:{item.task.strip().lower()}" for item in extraction.actions),
        *(f"decision:{item.summary.strip().lower()}" for item in extraction.decisions),
        *(f"question:{item.question.strip().lower()}" for item in extraction.open_questions),
    }


def entity_f1(actual: MeetingExtraction, expected: MeetingExtraction) -> float:
    actual_keys = entity_keys(actual)
    expected_keys = entity_keys(expected)
    if not actual_keys and not expected_keys:
        return 1.0
    true_positives = len(actual_keys & expected_keys)
    precision = true_positives / len(actual_keys) if actual_keys else 0.0
    recall = true_positives / len(expected_keys) if expected_keys else 0.0
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def _typed_entities(extraction: MeetingExtraction) -> list[tuple[str, str]]:
    return [
        *(("action", item.task.strip()) for item in extraction.actions),
        *(("decision", item.summary.strip()) for item in extraction.decisions),
        *(("question", item.question.strip()) for item in extraction.open_questions),
    ]


@lru_cache(maxsize=1)
def _semantic_model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")


def semantic_entity_f1(
    actual: MeetingExtraction,
    expected: MeetingExtraction,
    threshold: float = 0.72,
    similarity: Callable[[str, str], float] | None = None,
) -> float:
    actual_entities = _typed_entities(actual)
    expected_entities = _typed_entities(expected)
    if not actual_entities and not expected_entities:
        return 1.0
    if actual_entities == expected_entities:
        return 1.0

    embedding_by_text = {}
    if similarity is None:
        unique_texts = list(dict.fromkeys(text for _, text in [*actual_entities, *expected_entities]))
        embeddings = _semantic_model().encode(unique_texts, normalize_embeddings=True)
        embedding_by_text = dict(zip(unique_texts, embeddings, strict=True))

        def similarity(left: str, right: str) -> float:
            return float(embedding_by_text[left] @ embedding_by_text[right])

    candidates = sorted(
        (
            (similarity(actual_text, expected_text), actual_index, expected_index)
            for actual_index, (actual_type, actual_text) in enumerate(actual_entities)
            for expected_index, (expected_type, expected_text) in enumerate(expected_entities)
            if actual_type == expected_type
        ),
        reverse=True,
    )
    matched_actual: set[int] = set()
    matched_expected: set[int] = set()
    for score, actual_index, expected_index in candidates:
        if score < threshold:
            break
        if actual_index not in matched_actual and expected_index not in matched_expected:
            matched_actual.add(actual_index)
            matched_expected.add(expected_index)

    true_positives = len(matched_actual)
    precision = true_positives / len(actual_entities) if actual_entities else 0.0
    recall = true_positives / len(expected_entities) if expected_entities else 0.0
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


async def judge_extraction(
    transcript: str,
    actual: MeetingExtraction,
    expected: MeetingExtraction,
) -> JudgeScores:
    model = judge_model_name()
    prompt = (
        f"Numbered transcript:\n{NumberedTranscript.from_text(transcript).prompt_text()}\n\n"
        f"Reference extraction:\n{expected.model_dump_json(indent=2)}\n\n"
        f"Candidate extraction:\n{actual.model_dump_json(indent=2)}"
    )
    return await _run_structured(
        "ExtractionJudge",
        "Act as a strict independent evaluator. Compare the candidate with the reference and "
        "source transcript. Score correctness, completeness, and grounding from 1 (poor) to 5 "
        "(excellent). Penalize invented facts, missing substantive records, inaccurate owners or "
        "deadlines, and evidence that does not support its record. Treat semantically equivalent "
        "wording as correct. Give a concise rationale that names the most important strength or "
        "failure. Do not favor any extraction architecture.",
        prompt,
        JudgeScores,
        model=model,
    )


async def evaluate_case(case: dict[str, Any], strategy: ExtractionStrategy) -> dict[str, Any]:
    started = time.perf_counter()
    actual = await extract_meeting(case["transcript"], case["title"], strategy)
    elapsed = time.perf_counter() - started
    expected = MeetingExtraction.model_validate(case["expected"])
    transcript = NumberedTranscript.from_text(case["transcript"])
    records = [*actual.actions, *actual.decisions, *actual.open_questions]
    evidence_count = sum(len(record.evidence) for record in records)
    grounding_errors = validate_grounding(actual, transcript)
    judge = await judge_extraction(case["transcript"], actual, expected)
    return {
        "case": case["id"],
        "strategy": strategy.value,
        "entity_f1": round(entity_f1(actual, expected), 4),
        "semantic_entity_f1": round(semantic_entity_f1(actual, expected), 4),
        "grounding_rate": round(1 - len(grounding_errors) / max(evidence_count, 1), 4),
        "latency_seconds": round(elapsed, 3),
        "model_calls": MODEL_CALLS[strategy],
        "judge_correctness": judge.correctness,
        "judge_completeness": judge.completeness,
        "judge_grounding": judge.grounding,
        "judge_average": round(
            (judge.correctness + judge.completeness + judge.grounding) / 3,
            2,
        ),
        "judge_rationale": judge.rationale,
        "judge_model_calls": 1,
        "judge_model": os.getenv(JUDGE_MODEL_ENV, "test-double"),
        "candidate_extraction": actual.model_dump(mode="json"),
    }


async def run_evaluation(dataset_path: Path, split: str | None = "test") -> list[dict[str, Any]]:
    cases = json.loads(dataset_path.read_text(encoding="utf-8"))
    results: list[dict[str, Any]] = []
    for case in cases:
        if split and case.get("split") and case["split"] != split:
            continue
        for strategy in MODEL_CALLS:
            results.append(await evaluate_case(case, strategy))
    return results


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path, nargs="?", default=Path("evaluation/meetings.json"))
    parser.add_argument("--output", type=Path, default=Path("evaluation/results.json"))
    parser.add_argument("--split", choices=("development", "test", "all"), default="test")
    args = parser.parse_args()
    results = asyncio.run(run_evaluation(args.dataset, None if args.split == "all" else args.split))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()