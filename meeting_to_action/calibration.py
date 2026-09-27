"""Create blinded human-review packets and measure judge agreement."""

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

DIMENSIONS = ("correctness", "completeness", "grounding")
MIN_COMPLETED_RATINGS = 36
MAX_ACCEPTABLE_MAE = 0.75
MIN_WITHIN_ONE_RATE = 0.80


def candidate_id(case_id: str, strategy: str) -> str:
    digest = hashlib.sha256(f"{case_id}\0{strategy}".encode()).hexdigest()[:12]
    return f"candidate-{digest}"


def create_review_template(
    dataset_path: Path,
    results_path: Path,
    packet_path: Path,
    ratings_path: Path,
    sample_cases: int = 6,
) -> tuple[int, int]:
    cases = {case["id"]: case for case in json.loads(dataset_path.read_text(encoding="utf-8"))}
    results = json.loads(results_path.read_text(encoding="utf-8"))
    test_ids = sorted(case_id for case_id, case in cases.items() if case.get("split") == "test")
    selected_ids = set((test_ids or sorted(cases))[:sample_cases])
    selected_results = [result for result in results if result["case"] in selected_ids]
    if not selected_results:
        raise ValueError("No evaluation results match the selected calibration cases")
    if any("candidate_extraction" not in result for result in selected_results):
        raise ValueError("Rerun evaluation to include candidate_extraction before calibration")

    packet = []
    for result in selected_results:
        case = cases[result["case"]]
        packet.append(
            {
                "candidate_id": candidate_id(result["case"], result["strategy"]),
                "case_id": result["case"],
                "transcript": case["transcript"],
                "reference": case["expected"],
                "candidate": result["candidate_extraction"],
                "rubric": {
                    "correctness": "1=mostly wrong or invented; 5=fully correct",
                    "completeness": "1=misses most substantive outcomes; 5=complete",
                    "grounding": "1=unsupported evidence; 5=all records supported",
                },
            }
        )
    packet.sort(key=lambda item: item["candidate_id"])
    packet_path.parent.mkdir(parents=True, exist_ok=True)
    packet_path.write_text(json.dumps(packet, indent=2), encoding="utf-8")

    ratings_path.parent.mkdir(parents=True, exist_ok=True)
    with ratings_path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(
            output,
            fieldnames=["candidate_id", "reviewer", *DIMENSIONS, "comments"],
        )
        writer.writeheader()
        for item in packet:
            for reviewer in ("reviewer-1", "reviewer-2"):
                writer.writerow({"candidate_id": item["candidate_id"], "reviewer": reviewer})
    return len(packet), len(packet) * 2


def _completed_ratings(ratings_path: Path) -> list[dict[str, Any]]:
    completed = []
    with ratings_path.open(encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source):
            if not all(row.get(dimension, "").strip() for dimension in DIMENSIONS):
                continue
            scores = {dimension: int(row[dimension]) for dimension in DIMENSIONS}
            if any(score < 1 or score > 5 for score in scores.values()):
                raise ValueError("Human ratings must be integers from 1 to 5")
            completed.append({**row, **scores})
    return completed


def score_calibration(results_path: Path, ratings_path: Path) -> dict[str, Any]:
    results = json.loads(results_path.read_text(encoding="utf-8"))
    judge_scores = {
        candidate_id(result["case"], result["strategy"]): {
            dimension: result[f"judge_{dimension}"] for dimension in DIMENSIONS
        }
        for result in results
    }
    ratings = _completed_ratings(ratings_path)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rating in ratings:
        if rating["candidate_id"] in judge_scores:
            grouped[rating["candidate_id"]].append(rating)

    dimension_errors: dict[str, list[float]] = defaultdict(list)
    within_one: list[bool] = []
    inter_reviewer_errors: list[float] = []
    for opaque_id, candidate_ratings in grouped.items():
        human_scores = {
            dimension: mean(rating[dimension] for rating in candidate_ratings)
            for dimension in DIMENSIONS
        }
        for dimension in DIMENSIONS:
            error = abs(judge_scores[opaque_id][dimension] - human_scores[dimension])
            dimension_errors[dimension].append(error)
            within_one.append(error <= 1)
        if len(candidate_ratings) >= 2:
            first, second = candidate_ratings[:2]
            inter_reviewer_errors.extend(
                abs(first[dimension] - second[dimension]) for dimension in DIMENSIONS
            )

    completed_count = len(ratings)
    mae = {
        dimension: round(mean(errors), 3) if errors else None
        for dimension, errors in ((dimension, dimension_errors[dimension]) for dimension in DIMENSIONS)
    }
    overall_mae = round(mean(error for errors in dimension_errors.values() for error in errors), 3) if grouped else None
    within_one_rate = round(sum(within_one) / len(within_one), 3) if within_one else None
    calibrated = (
        completed_count >= MIN_COMPLETED_RATINGS
        and overall_mae is not None
        and overall_mae <= MAX_ACCEPTABLE_MAE
        and within_one_rate is not None
        and within_one_rate >= MIN_WITHIN_ONE_RATE
    )
    return {
        "status": "calibrated" if calibrated else "not calibrated",
        "completed_ratings": completed_count,
        "rated_candidates": len(grouped),
        "judge_human_mae": mae,
        "judge_human_overall_mae": overall_mae,
        "judge_human_within_one_rate": within_one_rate,
        "inter_reviewer_mae": round(mean(inter_reviewer_errors), 3) if inter_reviewer_errors else None,
        "thresholds": {
            "minimum_completed_ratings": MIN_COMPLETED_RATINGS,
            "maximum_overall_mae": MAX_ACCEPTABLE_MAE,
            "minimum_within_one_rate": MIN_WITHIN_ONE_RATE,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    template = subparsers.add_parser("template")
    template.add_argument("--dataset", type=Path, default=Path("evaluation/meetings.json"))
    template.add_argument("--results", type=Path, default=Path("evaluation/results.json"))
    template.add_argument("--packet", type=Path, default=Path("evaluation/calibration_packet.json"))
    template.add_argument("--ratings", type=Path, default=Path("evaluation/human_ratings.csv"))
    template.add_argument("--sample-cases", type=int, default=6)
    score = subparsers.add_parser("score")
    score.add_argument("--results", type=Path, default=Path("evaluation/results.json"))
    score.add_argument("--ratings", type=Path, default=Path("evaluation/human_ratings.csv"))
    score.add_argument("--output", type=Path, default=Path("evaluation/calibration_results.json"))
    args = parser.parse_args()

    if args.command == "template":
        candidates, rating_rows = create_review_template(
            args.dataset, args.results, args.packet, args.ratings, args.sample_cases
        )
        print(f"Wrote {candidates} blinded candidates and {rating_rows} reviewer rows")
    else:
        report = score_calibration(args.results, args.ratings)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()