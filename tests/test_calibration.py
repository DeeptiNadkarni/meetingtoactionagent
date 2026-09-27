import csv
import json

from meeting_to_action.calibration import candidate_id, create_review_template, score_calibration


def test_calibration_template_is_blinded_and_scoring_measures_agreement(tmp_path) -> None:
    dataset = [
        {
            "id": "case-1",
            "split": "test",
            "transcript": "Action: Publish brief.",
            "expected": {"title": "Review", "summary": "Brief assigned."},
        }
    ]
    results = [
        {
            "case": "case-1",
            "strategy": "Single model",
            "candidate_extraction": {"title": "Review", "summary": "Brief assigned."},
            "judge_correctness": 5,
            "judge_completeness": 4,
            "judge_grounding": 5,
        }
    ]
    dataset_path = tmp_path / "meetings.json"
    results_path = tmp_path / "results.json"
    packet_path = tmp_path / "packet.json"
    ratings_path = tmp_path / "ratings.csv"
    dataset_path.write_text(json.dumps(dataset), encoding="utf-8")
    results_path.write_text(json.dumps(results), encoding="utf-8")

    assert create_review_template(dataset_path, results_path, packet_path, ratings_path, 1) == (1, 2)
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    assert "strategy" not in packet[0]
    assert "judge_correctness" not in packet[0]

    opaque_id = candidate_id("case-1", "Single model")
    with ratings_path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(
            output,
            fieldnames=["candidate_id", "reviewer", "correctness", "completeness", "grounding", "comments"],
        )
        writer.writeheader()
        for reviewer in ("reviewer-1", "reviewer-2"):
            writer.writerow(
                {
                    "candidate_id": opaque_id,
                    "reviewer": reviewer,
                    "correctness": 5,
                    "completeness": 4,
                    "grounding": 5,
                    "comments": "Grounded and complete.",
                }
            )

    report = score_calibration(results_path, ratings_path)
    assert report["status"] == "not calibrated"
    assert report["completed_ratings"] == 2
    assert report["judge_human_overall_mae"] == 0.0
    assert report["inter_reviewer_mae"] == 0.0