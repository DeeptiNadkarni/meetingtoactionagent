"""Build reviewed, grounded SFT datasets without leaking frozen evaluation meetings."""

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from meeting_to_action.extraction import GROUNDING_RULES
from meeting_to_action.models import MeetingExtraction
from meeting_to_action.transcript import NumberedTranscript, validate_grounding

FROZEN_AMI_TEST_IDS = frozenset(
    {
        "ami-es2002c",
        "ami-es2007c",
        "ami-es2013b",
        "ami-es2013d",
        "ami-is1005c",
        "ami-ts3011b",
    }
)
SYSTEM_MESSAGE = f"Extract a complete meeting record. {GROUNDING_RULES}"


@dataclass(frozen=True)
class SftExample:
    source_id: str
    title: str
    transcript: str
    extraction: MeetingExtraction
    source: dict[str, Any]

    def training_record(self) -> dict[str, list[dict[str, str]]]:
        numbered = NumberedTranscript.from_text(self.transcript)
        return {
            "messages": [
                {"role": "system", "content": SYSTEM_MESSAGE},
                {
                    "role": "user",
                    "content": (
                        f"Meeting title: {self.title}\n\n"
                        f"Numbered transcript:\n{numbered.prompt_text()}"
                    ),
                },
                {
                    "role": "assistant",
                    "content": self.extraction.model_dump_json(exclude={"warnings"}),
                },
            ]
        }


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(cases, list):
        raise ValueError("AMI candidate data must be a JSON array")
    return cases


def load_reviewed_extractions(path: Path) -> dict[str, MeetingExtraction]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Reviewed extractions must be a JSON object keyed by source case ID")
    reviewed: dict[str, MeetingExtraction] = {}
    for source_id, record in payload.items():
        if not isinstance(record, dict):
            raise ValueError(f"{source_id}: review record must be a JSON object")
        if record.get("status") != "approved":
            raise ValueError(f"{source_id}: review status must be approved")
        reviewer = str(record.get("reviewer", "")).strip()
        reviewed_at = str(record.get("reviewed_at", "")).strip()
        if not reviewer:
            raise ValueError(f"{source_id}: reviewer is required")
        try:
            datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError(f"{source_id}: reviewed_at must be an ISO-8601 timestamp") from error
        reviewed[source_id] = MeetingExtraction.model_validate(record.get("extraction"))
    return reviewed


def validate_sft_examples(examples: list[SftExample]) -> list[str]:
    errors: list[str] = []
    seen_ids: set[str] = set()
    for example in examples:
        if example.source_id in seen_ids:
            errors.append(f"{example.source_id}: duplicate source meeting")
        seen_ids.add(example.source_id)
        if example.source_id in FROZEN_AMI_TEST_IDS:
            errors.append(f"{example.source_id}: frozen test meeting cannot be used for training")
        if example.extraction.title != example.title:
            errors.append(f"{example.source_id}: reviewed title does not match the source title")
        try:
            transcript = NumberedTranscript.from_text(example.transcript)
        except ValueError as error:
            errors.append(f"{example.source_id}: {error}")
            continue
        errors.extend(
            f"{example.source_id}: {error}"
            for error in validate_grounding(example.extraction, transcript)
        )
    return errors


def build_sft_examples(
    cases: list[dict[str, Any]],
    reviewed_extractions: dict[str, MeetingExtraction],
) -> list[SftExample]:
    eligible: list[dict[str, Any]] = []
    seen_case_ids: set[str] = set()
    for case in cases:
        source_id = str(case.get("id", "")).strip()
        split = case.get("split")
        if not source_id:
            raise ValueError("Every AMI candidate must have an ID")
        if source_id in seen_case_ids:
            raise ValueError(f"Duplicate AMI candidate ID: {source_id}")
        seen_case_ids.add(source_id)
        if source_id in FROZEN_AMI_TEST_IDS:
            if split != "test":
                raise ValueError(f"Frozen meeting {source_id} must remain in the test split")
            continue
        if split == "test":
            continue
        if split != "development":
            raise ValueError(f"{source_id}: unsupported split {split!r}")
        eligible.append(case)

    eligible_ids = {str(case["id"]) for case in eligible}
    missing_reviews = sorted(eligible_ids - reviewed_extractions.keys())
    unknown_reviews = sorted(reviewed_extractions.keys() - eligible_ids)
    if missing_reviews:
        raise ValueError("Missing reviewed extractions for: " + ", ".join(missing_reviews))
    if unknown_reviews:
        raise ValueError("Reviewed extractions are not eligible for training: " + ", ".join(unknown_reviews))

    examples = [
        SftExample(
            source_id=str(case["id"]),
            title=str(case["title"]),
            transcript=str(case["transcript"]),
            extraction=reviewed_extractions[str(case["id"])],
            source=dict(case.get("source", {})),
        )
        for case in eligible
    ]
    errors = validate_sft_examples(examples)
    if errors:
        raise ValueError("Invalid SFT examples:\n" + "\n".join(errors))
    return sorted(examples, key=lambda example: example.source_id)


def partition_examples(
    examples: list[SftExample],
    validation_every: int = 5,
) -> tuple[list[SftExample], list[SftExample]]:
    if validation_every < 2:
        raise ValueError("validation_every must be at least 2")
    validation = [example for index, example in enumerate(examples) if index % validation_every == 0]
    training = [example for index, example in enumerate(examples) if index % validation_every != 0]
    return training, validation


def _write_jsonl(path: Path, examples: list[SftExample]) -> None:
    content = "\n".join(
        json.dumps(example.training_record(), separators=(",", ":")) for example in examples
    )
    path.write_text(f"{content}\n" if content else "", encoding="utf-8")


def write_sft_dataset(examples: list[SftExample], output_directory: Path) -> dict[str, Any]:
    errors = validate_sft_examples(examples)
    if errors:
        raise ValueError("Invalid SFT examples:\n" + "\n".join(errors))
    training, validation = partition_examples(examples)
    output_directory.mkdir(parents=True, exist_ok=True)
    _write_jsonl(output_directory / "training.jsonl", training)
    _write_jsonl(output_directory / "validation.jsonl", validation)

    manifest = {
        "format_version": 1,
        "training_count": len(training),
        "validation_count": len(validation),
        "frozen_test_ids": sorted(FROZEN_AMI_TEST_IDS),
        "training_sources": [example.source_id for example in training],
        "validation_sources": [example.source_id for example in validation],
        "examples": [
            {
                "source_id": example.source_id,
                "source": example.source,
                "transcript_sha256": hashlib.sha256(example.transcript.encode("utf-8")).hexdigest(),
                "target_sha256": hashlib.sha256(
                    example.extraction.model_dump_json(exclude={"warnings"}).encode("utf-8")
                ).hexdigest(),
            }
            for example in examples
        ],
    }
    (output_directory / "manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--reviews", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("evaluation/sft.local"))
    args = parser.parse_args()

    examples = build_sft_examples(load_cases(args.cases), load_reviewed_extractions(args.reviews))
    manifest = write_sft_dataset(examples, args.output)
    print(
        f"Wrote {manifest['training_count']} training and "
        f"{manifest['validation_count']} validation examples to {args.output}"
    )


if __name__ == "__main__":
    main()