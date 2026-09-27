import asyncio

from meeting_to_action import evaluation
from meeting_to_action.evaluation import (
    JudgeScores,
    entity_f1,
    evaluate_case,
    judge_extraction,
    run_evaluation,
    semantic_entity_f1,
)
from meeting_to_action.extraction import ExtractionStrategy
from meeting_to_action.models import ActionItem, Evidence, MeetingExtraction


def test_entity_f1_scores_exact_entities() -> None:
    evidence = Evidence(quote="Action: Publish brief.", line_start=1, line_end=1)
    expected = MeetingExtraction(
        title="Review",
        summary="Brief assigned.",
        actions=[ActionItem(id="A1", task="Publish brief", evidence=[evidence])],
    )

    assert entity_f1(expected, expected) == 1.0
    assert entity_f1(MeetingExtraction(title="Review", summary="None"), expected) == 0.0


def test_semantic_entity_f1_matches_paraphrases_one_to_one_within_type() -> None:
    evidence = Evidence(quote="Action: Publish brief.", line_start=1, line_end=1)
    expected = MeetingExtraction(
        title="Review",
        summary="Brief assigned.",
        actions=[ActionItem(id="A1", task="Publish the customer brief", evidence=[evidence])],
    )
    actual = MeetingExtraction(
        title="Review",
        summary="Brief assigned.",
        actions=[
            ActionItem(id="A1", task="Release the customer briefing document", evidence=[evidence]),
            ActionItem(id="A2", task="Release the customer briefing document", evidence=[evidence]),
        ],
    )

    def similarity(left: str, right: str) -> float:
        return 0.9 if "customer" in left.lower() and "customer" in right.lower() else 0.1

    assert entity_f1(actual, expected) == 0.0
    assert semantic_entity_f1(actual, expected, similarity=similarity) == 2 / 3


def test_semantic_entity_f1_does_not_match_across_entity_types() -> None:
    evidence = Evidence(quote="Decision: Publish brief.", line_start=1, line_end=1)
    expected = MeetingExtraction(
        title="Review",
        summary="Brief assigned.",
        actions=[ActionItem(id="A1", task="Publish brief", evidence=[evidence])],
    )
    actual = MeetingExtraction(
        title="Review",
        summary="Brief assigned.",
        decisions=[{"id": "D1", "summary": "Publish brief", "evidence": [evidence]}],
    )

    assert semantic_entity_f1(actual, expected, similarity=lambda left, right: 1.0) == 0.0


def test_judge_requires_a_different_configured_model(monkeypatch) -> None:
    extraction = MeetingExtraction(title="Review", summary="No outcomes.")
    monkeypatch.setenv("FOUNDRY_MODEL", "generator")
    monkeypatch.delenv("FOUNDRY_JUDGE_MODEL", raising=False)

    try:
        asyncio.run(judge_extraction("No outcomes.", extraction, extraction))
        raise AssertionError("Missing judge configuration should fail")
    except RuntimeError as error:
        assert "FOUNDRY_JUDGE_MODEL must name" in str(error)

    monkeypatch.setenv("FOUNDRY_JUDGE_MODEL", "generator")
    try:
        asyncio.run(judge_extraction("No outcomes.", extraction, extraction))
        raise AssertionError("Same-model judge configuration should fail")
    except RuntimeError as error:
        assert "must differ" in str(error)


def test_evaluation_defaults_to_frozen_test_split(monkeypatch, tmp_path) -> None:
    dataset_path = tmp_path / "meetings.json"
    dataset_path.write_text(
        '[{"id":"dev","split":"development"},{"id":"test","split":"test"}]',
        encoding="utf-8",
    )

    async def fake_evaluate_case(case, strategy):
        return {"case": case["id"], "strategy": strategy.value}

    monkeypatch.setattr(evaluation, "evaluate_case", fake_evaluate_case)
    results = asyncio.run(run_evaluation(dataset_path))

    assert len(results) == 3
    assert {result["case"] for result in results} == {"test"}


def test_evaluation_combines_quantitative_metrics_with_llm_judge(monkeypatch) -> None:
    evidence = Evidence(quote="Action: Publish brief.", line_start=1, line_end=1)
    expected = MeetingExtraction(
        title="Review",
        summary="Brief assigned.",
        actions=[ActionItem(id="A1", task="Publish brief", evidence=[evidence])],
    )
    case = {
        "id": "review-01",
        "title": "Review",
        "transcript": "Action: Publish brief.",
        "expected": expected.model_dump(mode="json"),
    }

    async def fake_extract_meeting(transcript, title, strategy):
        return expected

    async def fake_judge_extraction(transcript, actual, reference):
        return JudgeScores(
            correctness=5,
            completeness=4,
            grounding=5,
            rationale="The candidate is correct and grounded but slightly terse.",
        )

    monkeypatch.setattr(evaluation, "extract_meeting", fake_extract_meeting)
    monkeypatch.setattr(evaluation, "judge_extraction", fake_judge_extraction)

    result = asyncio.run(evaluate_case(case, ExtractionStrategy.SINGLE))

    assert result["entity_f1"] == 1.0
    assert result["semantic_entity_f1"] == 1.0
    assert result["grounding_rate"] == 1.0
    assert result["judge_correctness"] == 5
    assert result["judge_completeness"] == 4
    assert result["judge_grounding"] == 5
    assert result["judge_average"] == 4.67
    assert result["judge_model_calls"] == 1
    assert result["judge_model"] == "test-double"