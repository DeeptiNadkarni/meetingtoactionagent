"""Ranked retrieval over numbered meeting transcript lines."""

from dataclasses import dataclass
import re

from rank_bm25 import BM25Okapi

from meeting_to_action.transcript import NumberedTranscript

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "for",
    "from",
    "in",
    "is",
    "of",
    "on",
    "the",
    "this",
    "to",
    "was",
    "what",
    "who",
    "would",
    "you",
}


def _tokens(text: str) -> list[str]:
    return [token for token in TOKEN_PATTERN.findall(text.lower()) if token not in STOP_WORDS]


@dataclass(frozen=True)
class RetrievalResult:
    line_numbers: tuple[int, ...]
    lines: tuple[str, ...]

    def prompt_text(self) -> str:
        return "\n".join(
            f"{line_number}: {line}"
            for line_number, line in zip(self.line_numbers, self.lines)
        )


def retrieve_transcript(
    transcript: NumberedTranscript,
    query: str,
    *,
    top_k: int = 8,
    neighbor_lines: int = 1,
) -> RetrievalResult:
    corpus = [_tokens(line) or ["empty"] for line in transcript.lines]
    query_tokens = _tokens(query)
    scores = BM25Okapi(corpus).get_scores(query_tokens) if query_tokens else [0.0] * len(corpus)
    ranked = sorted(range(len(corpus)), key=lambda index: (-scores[index], index))
    positive = [index for index in ranked if scores[index] > 0]
    seeds = (positive or ranked)[: min(top_k, len(ranked))]

    selected: set[int] = set()
    for index in seeds:
        start = max(0, index - neighbor_lines)
        end = min(len(transcript.lines), index + neighbor_lines + 1)
        selected.update(range(start, end))

    indexes = sorted(selected)
    return RetrievalResult(
        line_numbers=tuple(index + 1 for index in indexes),
        lines=tuple(transcript.lines[index] for index in indexes),
    )