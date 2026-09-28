"""Generate resumable SFT review drafts anchored to AMI human annotations."""

import argparse
import asyncio
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from meeting_to_action.extraction import (
    DEFAULT_MODEL,
    MODEL_ENV,
    ExtractionStrategy,
    extract_meeting,
)
from meeting_to_action.models import MeetingExtraction
from meeting_to_action.sft_dataset import FROZEN_AMI_TEST_IDS, load_cases
from meeting_to_action.transcript import NumberedTranscript, validate_grounding


def merge_human_annotations(
    draft: MeetingExtraction,
    reference: MeetingExtraction,
) -> MeetingExtraction:
    return draft.model_copy(
        update={
            "title": reference.title,
            "actions": reference.actions,
            "decisions": reference.decisions,
            "open_questions": reference.open_questions,
            "warnings": [],
        }
    )


def _load_drafts(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Enrichment draft file must be a JSON object keyed by source case ID")
    return payload


def _write_drafts(path: Path, drafts: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(drafts, indent=2), encoding="utf-8")
    temporary.replace(path)


def review_draft(
    drafts: dict[str, Any],
    source_id: str,
    extraction: MeetingExtraction,
    transcript: str,
    reviewer: str,
    *,
    approved: bool,
    reviewed_at: datetime | None = None,
) -> dict[str, Any]:
    reviewer = reviewer.strip()
    if not reviewer:
        raise ValueError("Reviewer is required")
    if source_id not in drafts:
        raise KeyError(f"Unknown draft: {source_id}")
    grounding_errors = validate_grounding(extraction, NumberedTranscript.from_text(transcript))
    if grounding_errors:
        raise ValueError("Grounding validation failed: " + "; ".join(grounding_errors))

    updated = dict(drafts[source_id])
    updated.update(
        {
            "status": "approved" if approved else "rejected",
            "reviewer": reviewer,
            "reviewed_at": (reviewed_at or datetime.now(timezone.utc)).isoformat(),
            "extraction": extraction.model_dump(mode="json", exclude={"warnings"}),
        }
    )
    drafts[source_id] = updated
    return updated


def save_review_packet(path: Path, drafts: dict[str, Any]) -> None:
    _write_drafts(path, drafts)


async def generate_enrichment_drafts(
    cases: list[dict[str, Any]],
    output_path: Path,
    *,
    model: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    drafts = _load_drafts(output_path)
    eligible = [
        case
        for case in cases
        if case.get("split") == "development" and case.get("id") not in FROZEN_AMI_TEST_IDS
    ]
    generated = 0
    selected_model = model or os.getenv(MODEL_ENV, DEFAULT_MODEL)
    for case in eligible:
        source_id = str(case["id"])
        if source_id in drafts:
            continue
        if limit is not None and generated >= limit:
            break

        teacher_draft = await extract_meeting(
            str(case["transcript"]),
            str(case["title"]),
            ExtractionStrategy.SINGLE,
            model=model,
        )
        reference = MeetingExtraction.model_validate(case["expected"])
        extraction = merge_human_annotations(teacher_draft, reference)
        grounding_errors = validate_grounding(
            extraction,
            NumberedTranscript.from_text(str(case["transcript"])),
        )
        if grounding_errors:
            raise ValueError(f"{source_id}: " + "; ".join(grounding_errors))

        transcript = str(case["transcript"])
        drafts[source_id] = {
            "status": "draft",
            "reviewer": "",
            "reviewed_at": "",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "generated_by": selected_model,
            "annotation_policy": (
                "AMI human actions, decisions, and problems; teacher-generated summary and notes"
            ),
            "transcript_sha256": hashlib.sha256(transcript.encode("utf-8")).hexdigest(),
            "extraction": extraction.model_dump(mode="json", exclude={"warnings"}),
        }
        _write_drafts(output_path, drafts)
        generated += 1
        print(f"Drafted {source_id} ({len(drafts)}/{len(eligible)})", flush=True)
    return drafts


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("evaluation/reviewed_sft_extractions.local.json"),
    )
    parser.add_argument("--model", help="Optional teacher deployment; defaults to FOUNDRY_MODEL")
    parser.add_argument("--limit", type=int, help="Generate at most this many new drafts")
    args = parser.parse_args()

    drafts = asyncio.run(
        generate_enrichment_drafts(
            load_cases(args.cases),
            args.output,
            model=args.model,
            limit=args.limit,
        )
    )
    approved = sum(record.get("status") == "approved" for record in drafts.values())
    print(f"Review packet contains {len(drafts)} drafts; {approved} approved")


if __name__ == "__main__":
    main()