import pytest

from meeting_to_action.advanced_evaluation import (
    conflict_scores,
    diarization_label_accuracy,
    live_batch_agreement,
    timestamp_mean_absolute_error_ms,
    word_error_rate,
)


def test_word_error_rate_and_live_batch_agreement() -> None:
    assert word_error_rate("prepare the launch brief", "prepare launch brief") == 0.25
    assert live_batch_agreement("prepare launch brief", "prepare the launch brief") == 0.75


def test_timestamp_error_uses_segment_boundaries() -> None:
    error = timestamp_mean_absolute_error_ms(
        [(1_000, 2_000), (3_000, 4_000)],
        [(1_100, 2_100), (2_900, 4_200)],
    )

    assert error == 125.0


def test_diarization_accuracy_is_label_name_independent() -> None:
    assert diarization_label_accuracy(
        ["Maya", "Maya", "Jon"],
        ["Guest-1", "Guest-1", "Guest-2"],
    ) == 1.0
    with pytest.raises(ValueError, match="equal length"):
        diarization_label_accuracy(["Maya"], [])


def test_conflict_scores_compare_record_pairs() -> None:
    expected = {frozenset(("A1", "A2")), frozenset(("A3", "A4"))}
    actual = {frozenset(("A1", "A2")), frozenset(("A5", "A6"))}

    assert conflict_scores(expected, actual) == {"precision": 0.5, "recall": 0.5, "f1": 0.5}