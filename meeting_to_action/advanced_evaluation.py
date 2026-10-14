"""Deterministic metrics for advanced single-meeting capabilities."""

import re
from collections import Counter, defaultdict

WORD = re.compile(r"[a-z0-9']+")


def _words(text: str) -> list[str]:
    return WORD.findall(text.casefold())


def word_error_rate(reference: str, hypothesis: str) -> float:
    expected = _words(reference)
    actual = _words(hypothesis)
    if not expected:
        return 0.0 if not actual else 1.0
    previous = list(range(len(actual) + 1))
    for expected_word in expected:
        current = [previous[0] + 1]
        for index, actual_word in enumerate(actual, 1):
            current.append(min(
                current[-1] + 1,
                previous[index] + 1,
                previous[index - 1] + (expected_word != actual_word),
            ))
        previous = current
    return previous[-1] / len(expected)


def timestamp_mean_absolute_error_ms(
    reference: list[tuple[int, int]],
    actual: list[tuple[int, int]],
) -> float:
    if len(reference) != len(actual):
        raise ValueError("Reference and actual timestamp lists must have equal length")
    if not reference:
        return 0.0
    errors = [
        error
        for expected, observed in zip(reference, actual, strict=True)
        for error in (abs(expected[0] - observed[0]), abs(expected[1] - observed[1]))
    ]
    return sum(errors) / len(errors)


def diarization_label_accuracy(reference: list[str], actual: list[str]) -> float:
    if len(reference) != len(actual):
        raise ValueError("Reference and actual speaker lists must have equal length")
    if not reference:
        return 1.0
    votes: dict[str, Counter[str]] = defaultdict(Counter)
    for expected, observed in zip(reference, actual, strict=True):
        votes[observed][expected] += 1
    mapping = {observed: counts.most_common(1)[0][0] for observed, counts in votes.items()}
    return sum(mapping[observed] == expected for expected, observed in zip(reference, actual, strict=True)) / len(reference)


def conflict_scores(
    expected: set[frozenset[str]],
    actual: set[frozenset[str]],
) -> dict[str, float]:
    true_positives = len(expected & actual)
    precision = true_positives / len(actual) if actual else (1.0 if not expected else 0.0)
    recall = true_positives / len(expected) if expected else (1.0 if not actual else 0.0)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


def live_batch_agreement(live_transcript: str, batch_transcript: str) -> float:
    return max(0.0, 1.0 - word_error_rate(batch_transcript, live_transcript))