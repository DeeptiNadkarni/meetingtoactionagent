"""Build grounded extraction cases from the CC BY 4.0 AMI corpus."""

import argparse
import json
import re
import urllib.request
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from xml.etree import ElementTree

AMI_ARCHIVE_URL = (
    "https://groups.inf.ed.ac.uk/ami/AMICorpusAnnotations/ami_public_manual_1.6.2.zip"
)
AMI_LICENSE = "CC BY 4.0"
AMI_VERSION = "1.6.2"
NITE = "http://nite.sourceforge.net/"
HREF_PATTERN = re.compile(r"^(?P<file>[^#]+)#id\((?P<start>[^)]+)\)(?:\.\.id\((?P<end>[^)]+)\))?$")


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def nite_id(element: ElementTree.Element) -> str | None:
    return element.get(f"{{{NITE}}}id") or element.get("id")


def href_parts(href: str) -> tuple[str, str, str]:
    match = HREF_PATTERN.match(href)
    if not match:
        raise ValueError(f"Unsupported AMI href: {href}")
    return match.group("file"), match.group("start"), match.group("end") or match.group("start")


@dataclass(frozen=True)
class DialogueAct:
    id: str
    speaker: str
    text: str
    start_time: float


def read_words(path: Path) -> tuple[list[str], dict[str, int], dict[str, float]]:
    words: list[str] = []
    positions: dict[str, int] = {}
    times: dict[str, float] = {}
    for element in ElementTree.parse(path).getroot().iter():
        word_id = nite_id(element)
        if not word_id or local_name(element.tag) not in {"w", "vocalsound", "pause"}:
            continue
        text = "".join(element.itertext()).strip()
        if not text or local_name(element.tag) != "w":
            continue
        positions[word_id] = len(words)
        times[word_id] = float(element.get("starttime", "0"))
        words.append(text)
    return words, positions, times


def load_dialogue_acts(root: Path, meeting_id: str) -> list[DialogueAct]:
    word_data = {
        path.name: read_words(path)
        for path in sorted((root / "words").glob(f"{meeting_id}.*.words.xml"))
    }
    dialogue_acts: list[DialogueAct] = []
    for path in sorted((root / "dialogueActs").glob(f"{meeting_id}.*.dialog-act.xml")):
        speaker = path.name.split(".")[1]
        for element in ElementTree.parse(path).getroot():
            dialogue_id = nite_id(element)
            child = next((item for item in element if local_name(item.tag) == "child"), None)
            if not dialogue_id or child is None or not child.get("href"):
                continue
            word_file, start_id, end_id = href_parts(child.get("href", ""))
            if word_file not in word_data:
                continue
            words, positions, times = word_data[word_file]
            if start_id not in positions or end_id not in positions:
                continue
            start = positions[start_id]
            end = positions[end_id]
            text = " ".join(words[start : end + 1]).strip()
            text = re.sub(r"\s+([,.;:!?])", r"\1", text)
            if text:
                dialogue_acts.append(DialogueAct(dialogue_id, speaker, text, times[start_id]))
    return sorted(dialogue_acts, key=lambda item: (item.start_time, item.id))


def load_abstract_labels(root: Path, meeting_id: str) -> dict[str, tuple[str, str]]:
    labels: dict[str, tuple[str, str]] = {}
    path = root / "abstractive" / f"{meeting_id}.abssumm.xml"
    for category in ElementTree.parse(path).getroot():
        kind = local_name(category.tag)
        if kind not in {"actions", "decisions", "problems"}:
            continue
        for sentence in category:
            sentence_id = nite_id(sentence)
            text = " ".join("".join(sentence.itertext()).split())
            if sentence_id and text and text.rstrip(".").upper() != "NA":
                labels[sentence_id] = (kind, text)
    return labels


def load_summary_links(root: Path, meeting_id: str) -> dict[str, set[str]]:
    links: dict[str, set[str]] = defaultdict(set)
    path = root / "extractive" / f"{meeting_id}.summlink.xml"
    for element in ElementTree.parse(path).getroot():
        pointers = {pointer.get("role"): pointer.get("href") for pointer in element}
        if not pointers.get("extractive") or not pointers.get("abstractive"):
            continue
        _, dialogue_id, _ = href_parts(pointers["extractive"] or "")
        _, abstract_id, _ = href_parts(pointers["abstractive"] or "")
        links[abstract_id].add(dialogue_id)
    return links


def build_case(root: Path, meeting_id: str, context_lines: int = 1) -> dict | None:
    required_paths = (
        root / "abstractive" / f"{meeting_id}.abssumm.xml",
        root / "extractive" / f"{meeting_id}.summlink.xml",
    )
    if not all(path.is_file() for path in required_paths):
        return None
    dialogue_acts = load_dialogue_acts(root, meeting_id)
    dialogue_by_id = {item.id: item for item in dialogue_acts}
    dialogue_positions = {item.id: index for index, item in enumerate(dialogue_acts)}
    labels = load_abstract_labels(root, meeting_id)
    links = load_summary_links(root, meeting_id)
    grounded_labels = {
        label_id: (kind, text, sorted(dialogue_id for dialogue_id in links[label_id] if dialogue_id in dialogue_by_id))
        for label_id, (kind, text) in labels.items()
        if any(dialogue_id in dialogue_by_id for dialogue_id in links[label_id])
    }
    if not grounded_labels:
        return None

    selected_positions: set[int] = set()
    for _, _, dialogue_ids in grounded_labels.values():
        for dialogue_id in dialogue_ids:
            position = dialogue_positions[dialogue_id]
            selected_positions.update(
                range(max(0, position - context_lines), min(len(dialogue_acts), position + context_lines + 1))
            )
    selected = [dialogue_acts[position] for position in sorted(selected_positions)]
    line_numbers = {item.id: index for index, item in enumerate(selected, 1)}
    rendered_lines = [f"Speaker {item.speaker}: {item.text}" for item in selected]

    expected = {
        "title": f"AMI meeting {meeting_id}",
        "summary": "Human-annotated meeting outcomes from the AMI corpus.",
        "actions": [],
        "decisions": [],
        "open_questions": [],
    }
    counters = {"actions": 0, "decisions": 0, "problems": 0}
    for label_id, (kind, text, dialogue_ids) in sorted(grounded_labels.items()):
        evidence = [
            {
                "quote": rendered_lines[line_numbers[dialogue_id] - 1],
                "line_start": line_numbers[dialogue_id],
                "line_end": line_numbers[dialogue_id],
            }
            for dialogue_id in dialogue_ids
            if dialogue_id in line_numbers
        ]
        if not evidence:
            continue
        counters[kind] += 1
        if kind == "actions":
            expected["actions"].append(
                {"id": f"A{counters[kind]}", "task": text, "status": "proposed", "evidence": evidence}
            )
        elif kind == "decisions":
            expected["decisions"].append(
                {"id": f"D{counters[kind]}", "summary": text, "evidence": evidence}
            )
        else:
            expected["open_questions"].append(
                {"id": f"Q{counters[kind]}", "question": text, "evidence": evidence}
            )

    categories = [category for category, count in counters.items() if count]
    return {
        "id": f"ami-{meeting_id.lower()}",
        "title": f"AMI meeting {meeting_id}",
        "transcript": "\n".join(rendered_lines),
        "expected": expected,
        "source": {
            "dataset": "AMI Meeting Corpus",
            "meeting_id": meeting_id,
            "version": AMI_VERSION,
            "license": AMI_LICENSE,
            "url": "https://groups.inf.ed.ac.uk/ami/corpus/",
            "annotation": "human abstractive summary linked to source dialogue acts",
            "excerpt_context_lines": context_lines,
        },
        "categories": categories,
    }


def select_cases(cases: list[dict], count: int) -> list[dict]:
    selected: list[dict] = []
    remaining = sorted(cases, key=lambda case: case["id"])
    uncovered = {"actions", "decisions", "problems"}
    while remaining and len(selected) < count:
        best = max(
            remaining,
            key=lambda case: (
                len(set(case["categories"]) & uncovered),
                len(case["categories"]),
                sum(len(case["expected"][key]) for key in ("actions", "decisions", "open_questions")),
                tuple(-ord(character) for character in case["id"]),
            ),
        )
        selected.append(best)
        remaining.remove(best)
        uncovered -= set(best["categories"])
    for index, case in enumerate(selected):
        case["split"] = "test" if index % 4 == 0 else "development"
    return selected


def find_annotation_root(extracted: Path) -> Path:
    for path in extracted.rglob("abstractive"):
        candidate = path.parent
        if (candidate / "dialogueActs").is_dir() and (candidate / "extractive").is_dir():
            return candidate
    raise FileNotFoundError("AMI annotation directories were not found in the archive")


def build_benchmark(annotation_root: Path, count: int = 24, context_lines: int = 1) -> list[dict]:
    meeting_ids = sorted(path.name.removesuffix(".abssumm.xml") for path in (annotation_root / "abstractive").glob("*.abssumm.xml"))
    cases = [case for meeting_id in meeting_ids if (case := build_case(annotation_root, meeting_id, context_lines))]
    if len(cases) < count:
        raise ValueError(f"AMI produced {len(cases)} grounded cases; {count} requested")
    return select_cases(cases, count)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, help="Use an existing AMI annotation archive")
    parser.add_argument("--output", type=Path, default=Path("evaluation/meetings.json"))
    parser.add_argument("--count", type=int, default=24)
    parser.add_argument("--context-lines", type=int, default=1)
    args = parser.parse_args()

    with TemporaryDirectory(prefix="ami-benchmark-") as temporary_directory:
        temporary = Path(temporary_directory)
        archive = args.archive or temporary / "ami_public_manual_1.6.2.zip"
        if not args.archive:
            urllib.request.urlretrieve(AMI_ARCHIVE_URL, archive)
        with zipfile.ZipFile(archive) as source:
            source.extractall(temporary / "annotations")
        cases = build_benchmark(find_annotation_root(temporary / "annotations"), args.count, args.context_lines)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(cases, indent=2), encoding="utf-8")
    print(f"Wrote {len(cases)} AMI cases to {args.output}")


if __name__ == "__main__":
    main()