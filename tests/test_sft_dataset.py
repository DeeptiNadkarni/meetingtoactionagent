import json

import pytest

from meeting_to_action.models import ActionItem, Evidence, MeetingExtraction
from meeting_to_action.sft_dataset import (
    FROZEN_AMI_TEST_IDS,
    SftExample,
    build_sft_examples,
    load_reviewed_extractions,
    validate_sft_examples,
    write_sft_dataset,
)


def reviewed_extraction(title: str, quote: str = "Action: Publish the brief.") -> MeetingExtraction:
    return MeetingExtraction(
        title=title,
        summary="The brief was assigned.",
        actions=[
            ActionItem(
                id="A1",
                task="Publish the brief",
                evidence=[Evidence(quote=quote, line_start=1, line_end=1)],
            )
        ],
    )


def test_builder_excludes_test_cases_and_requires_reviewed_targets() -> None:
    cases = [
        {
            "id": "ami-dev001",
            "title": "AMI meeting DEV001",
            "transcript": "Action: Publish the brief.",
            "split": "development",
            "source": {"dataset": "AMI Meeting Corpus", "meeting_id": "DEV001"},
        },
        {
            "id": "ami-other-test",
            "title": "AMI meeting TEST001",
            "transcript": "Action: Do not train on this.",
            "split": "test",
            "source": {"dataset": "AMI Meeting Corpus", "meeting_id": "TEST001"},
        },
    ]
    reviews = {"ami-dev001": reviewed_extraction("AMI meeting DEV001")}

    examples = build_sft_examples(cases, reviews)

    assert [example.source_id for example in examples] == ["ami-dev001"]
    assert [message["role"] for message in examples[0].training_record()["messages"]] == [
        "system",
        "user",
        "assistant",
    ]


def test_builder_rejects_a_frozen_meeting_with_tampered_split() -> None:
    source_id = next(iter(FROZEN_AMI_TEST_IDS))
    cases = [
        {
            "id": source_id,
            "title": "Frozen",
            "transcript": "Action: Do not train.",
            "split": "development",
        }
    ]

    with pytest.raises(ValueError, match="must remain in the test split"):
        build_sft_examples(cases, {source_id: reviewed_extraction("Frozen", "Action: Do not train.")})


def test_validator_rejects_ungrounded_reviewed_output() -> None:
    example = SftExample(
        source_id="ami-dev001",
        title="Review",
        transcript="Action: Publish the brief.",
        extraction=reviewed_extraction("Review", "Action: Invent a deadline."),
        source={},
    )

    assert "quote is not present" in validate_sft_examples([example])[0]


def test_writer_keeps_training_and_validation_meetings_disjoint(tmp_path) -> None:
    examples = [
        SftExample(
            source_id=f"ami-dev{index:03d}",
            title=f"Review {index}",
            transcript="Action: Publish the brief.",
            extraction=reviewed_extraction(f"Review {index}"),
            source={"dataset": "AMI Meeting Corpus"},
        )
        for index in range(6)
    ]

    manifest = write_sft_dataset(examples, tmp_path)
    training_records = [
        json.loads(line)
        for line in (tmp_path / "training.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert manifest["training_count"] == 4
    assert manifest["validation_count"] == 2
    assert set(manifest["training_sources"]).isdisjoint(manifest["validation_sources"])
    assert set(manifest["frozen_test_ids"]) == FROZEN_AMI_TEST_IDS
    assert len(training_records) == 4
    assert set(training_records[0]) == {"messages"}


def test_review_loader_rejects_unapproved_model_drafts(tmp_path) -> None:
    review_path = tmp_path / "reviews.json"
    review_path.write_text(
        json.dumps(
            {
                "ami-dev001": {
                    "status": "draft",
                    "reviewer": "",
                    "reviewed_at": "",
                    "extraction": reviewed_extraction("Review").model_dump(mode="json"),
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="review status must be approved"):
        load_reviewed_extractions(review_path)


def test_review_loader_accepts_approved_review_metadata(tmp_path) -> None:
    review_path = tmp_path / "reviews.json"
    review_path.write_text(
        json.dumps(
            {
                "ami-dev001": {
                    "status": "approved",
                    "reviewer": "reviewer@example.com",
                    "reviewed_at": "2026-09-27T10:30:00Z",
                    "extraction": reviewed_extraction("Review").model_dump(mode="json"),
                }
            }
        ),
        encoding="utf-8",
    )

    reviewed = load_reviewed_extractions(review_path)

    assert reviewed["ami-dev001"].title == "Review"