"""Azure Speech fast transcription for uploaded and recorded meeting media."""

import os
from io import BytesIO
from pathlib import Path
from typing import Any

from meeting_to_action.advanced import TranscriptSegment
from meeting_to_action.ingestion import TranscriptDocument, TranscriptSource

MAX_MEDIA_BYTES = 300 * 1024 * 1024
SUPPORTED_MEDIA_EXTENSIONS = {
    ".aac",
    ".flac",
    ".m4a",
    ".mov",
    ".mp3",
    ".mp4",
    ".ogg",
    ".wav",
    ".webm",
    ".wma",
}


def speech_is_configured() -> bool:
    return bool(os.getenv("AZURE_SPEECH_ENDPOINT"))


def _credential() -> tuple[Any, bool]:
    api_key = os.getenv("AZURE_SPEECH_API_KEY")
    if api_key:
        from azure.core.credentials import AzureKeyCredential

        return AzureKeyCredential(api_key), False
    from azure.identity import DefaultAzureCredential

    return DefaultAzureCredential(exclude_interactive_browser_credential=True), True


def transcribe_media(
    filename: str,
    content: bytes,
    *,
    locales: list[str] | None = None,
    max_speakers: int = 6,
    client: Any | None = None,
) -> TranscriptDocument:
    if not content:
        raise ValueError("Recording is empty")
    if len(content) > MAX_MEDIA_BYTES:
        raise ValueError("Recording exceeds the 300 MB fast-transcription limit")
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_MEDIA_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_MEDIA_EXTENSIONS))
        raise ValueError(f"Unsupported recording type. Supported types: {supported}")
    if not 2 <= max_speakers <= 35:
        raise ValueError("max_speakers must be between 2 and 35")

    from azure.ai.transcription import TranscriptionClient
    from azure.ai.transcription.models import (
        TranscriptionContent,
        TranscriptionDiarizationOptions,
        TranscriptionOptions,
    )

    endpoint = os.getenv("AZURE_SPEECH_ENDPOINT", "").strip()
    if client is None and not endpoint:
        raise RuntimeError("AZURE_SPEECH_ENDPOINT is not configured")

    credential = None
    close_credential = False
    transcription_client = client
    if transcription_client is None:
        credential, close_credential = _credential()
        transcription_client = TranscriptionClient(endpoint=endpoint, credential=credential)

    audio = BytesIO(content)
    audio.name = filename
    try:
        options = TranscriptionOptions(
            locales=locales or ["en-US"],
            diarization_options=TranscriptionDiarizationOptions(max_speakers=max_speakers),
        )
        result = transcription_client.transcribe(
            TranscriptionContent(definition=options, audio=audio)
        )
    finally:
        if client is None:
            transcription_client.close()
        if close_credential:
            credential.close()

    segments = [
        TranscriptSegment(
            id=f"S{index}",
            text=str(phrase.text).strip(),
            start_ms=int(phrase.offset_milliseconds),
            end_ms=int(phrase.offset_milliseconds + phrase.duration_milliseconds),
            speaker=f"Speaker {phrase.speaker}" if phrase.speaker is not None else None,
            locale=str(phrase.locale) if phrase.locale else None,
        )
        for index, phrase in enumerate(result.phrases or [], 1)
        if str(phrase.text).strip()
    ]
    if not segments:
        raise ValueError("Azure Speech returned no recognized phrases")
    text = "\n".join(
        f"{segment.speaker}: {segment.text}" if segment.speaker else segment.text
        for segment in segments
    )
    return TranscriptDocument.create(
        source=TranscriptSource.UPLOAD,
        external_id="speech-fast-transcription",
        title=Path(filename).stem,
        filename=filename,
        text=text,
        raw_content=content,
        content_type=None,
        metadata={
            "segments": [segment.model_dump(mode="json") for segment in segments],
            "transcription": "Azure Speech fast transcription",
        },
    )


def segments_from_document(document: TranscriptDocument) -> list[TranscriptSegment]:
    return [TranscriptSegment.model_validate(item) for item in document.metadata.get("segments", [])]