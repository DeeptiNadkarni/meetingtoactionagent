from email.message import EmailMessage

import pytest

from meeting_to_action.ingestion import MAX_TRANSCRIPT_BYTES, parse_uploaded_transcript


def test_text_upload_has_stable_hash_and_metadata() -> None:
    document = parse_uploaded_transcript("Weekly Sync.txt", b"Maya: Ship the brief Friday.")

    assert document.title == "Weekly Sync"
    assert document.text == "Maya: Ship the brief Friday."
    assert len(document.content_hash) == 64


def test_vtt_upload_removes_cues_and_timestamps() -> None:
    document = parse_uploaded_transcript(
        "meeting.vtt",
        b"WEBVTT\n\n1\n00:00:01.000 --> 00:00:03.000\nMaya: Hello.\n",
    )

    assert document.text == "Maya: Hello."


def test_teams_vtt_upload_removes_uuid_cues_and_normalizes_voice_tags() -> None:
    document = parse_uploaded_transcript(
        "meeting.vtt",
        (
            b"WEBVTT\n\n"
            b"c61ee08c-a4de-4641-b68d-561b1842a198/118-0\n"
            b"00:00:01.000 --> 00:00:03.000\n"
            b"<v Mansi Mishra>We have revamped the\n"
            b"guest pass UI.</v>\n\n"
            b"c61ee08c-a4de-4641-b68d-561b1842a198/118-1\n"
            b"00:00:03.000 --> 00:00:04.000\n"
            b"<v Mansi Mishra>It now supports sponsor actions.</v>\n\n"
            b"c61ee08c-a4de-4641-b68d-561b1842a198/118-2\n"
            b"00:00:04.000 --> 00:00:05.000\n"
            b"<v Allwyn Stanley>Approvals are no longer needed.</v>\n"
        ),
    )

    assert document.text == (
        "Mansi Mishra: We have revamped the guest pass UI. It now supports sponsor actions.\n"
        "Allwyn Stanley: Approvals are no longer needed."
    )


def test_eml_uses_supported_attachment() -> None:
    message = EmailMessage()
    message["Subject"] = "Customer review"
    message.set_content("See attached.")
    message.add_attachment(
        b"Decision: Launch Friday.",
        maintype="text",
        subtype="plain",
        filename="transcript.txt",
    )

    document = parse_uploaded_transcript("message.eml", message.as_bytes())

    assert document.title == "Customer review"
    assert document.text == "Decision: Launch Friday."
    assert document.metadata["attachment"] == "transcript.txt"


def test_upload_rejects_unsupported_and_oversized_files() -> None:
    with pytest.raises(ValueError, match="Unsupported"):
        parse_uploaded_transcript("meeting.pdf", b"content")
    with pytest.raises(ValueError, match="10 MB"):
        parse_uploaded_transcript("meeting.txt", b"x" * (MAX_TRANSCRIPT_BYTES + 1))