from dataclasses import dataclass

from meeting_to_action.connectors import MicrosoftGraphConnector, RemoteTranscript, ZoomConnector
from meeting_to_action.ingestion import TranscriptSource


@dataclass
class FakeResponse:
    payload: dict
    content: bytes = b""
    status_code: int = 200
    text: str = ""
    headers: dict | None = None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return self.responses.pop(0)

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self.responses.pop(0)


def test_graph_search_filters_supported_transcript_files() -> None:
    session = FakeSession(
        [FakeResponse({"value": [
            {"id": "one", "name": "sync.vtt", "parentReference": {"driveId": "drive"}},
            {"id": "two", "name": "slides.pptx", "parentReference": {"driveId": "drive"}},
        ]})]
    )
    connector = MicrosoftGraphConnector("token", session=session)

    items = connector.search_files("sync")

    assert [item.name for item in items] == ["sync.vtt"]
    assert items[0].metadata["drive_id"] == "drive"


def test_graph_download_parses_remote_file() -> None:
    session = FakeSession(
        [FakeResponse({}, content=b"Decision: Ship Friday.", headers={"Content-Type": "text/plain"})]
    )
    connector = MicrosoftGraphConnector("token", session=session)
    item = RemoteTranscript(
        id="one",
        name="sync.txt",
        source=TranscriptSource.MICROSOFT_365,
        metadata={"drive_id": "drive"},
    )

    document = connector.download_file(item)

    assert document.text == "Decision: Ship Friday."
    assert document.source is TranscriptSource.MICROSOFT_365


def test_zoom_lists_and_downloads_transcript() -> None:
    session = FakeSession([
        FakeResponse({"access_token": "zoom-token"}),
        FakeResponse({"meetings": [{
            "topic": "Weekly sync",
            "recording_files": [{
                "id": "transcript-id",
                "file_type": "TRANSCRIPT",
                "download_url": "https://zoom.test/transcript",
            }],
        }]}),
        FakeResponse({}, content=b"WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nMaya: Hello."),
    ])
    connector = ZoomConnector("account", "client", "secret", "user@example.com", session=session)

    item = connector.list_transcripts()[0]
    document = connector.download(item)

    assert item.name == "Weekly sync.vtt"
    assert document.text == "Maya: Hello."
    assert document.source is TranscriptSource.ZOOM