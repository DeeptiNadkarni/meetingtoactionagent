"""Remote transcript source connectors."""

import base64
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
from pydantic import BaseModel, Field

from meeting_to_action.ingestion import (
    SUPPORTED_EXTENSIONS,
    TranscriptDocument,
    TranscriptSource,
    parse_uploaded_transcript,
)

GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
MICROSOFT_SCOPES = [
    "Files.Read",
    "Calendars.Read",
    "OnlineMeetings.Read",
    "OnlineMeetingTranscript.Read.All",
    "Mail.Read",
]
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
]


class ConnectorError(RuntimeError):
    pass


class RemoteTranscript(BaseModel):
    id: str
    name: str
    source: TranscriptSource
    modified_at: str | None = None
    detail: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


def _supported_name(name: str) -> bool:
    return Path(name).suffix.lower() in SUPPORTED_EXTENSIONS - {".eml"}


def _as_source(document: TranscriptDocument, source: TranscriptSource, external_id: str) -> TranscriptDocument:
    return document.model_copy(update={"source": source, "external_id": external_id})


class MicrosoftDeviceAuth:
    def __init__(self, client_id: str, tenant_id: str = "organizations") -> None:
        import msal

        self.application = msal.PublicClientApplication(
            client_id,
            authority=f"https://login.microsoftonline.com/{tenant_id}",
        )

    def start(self) -> dict[str, Any]:
        flow = self.application.initiate_device_flow(scopes=MICROSOFT_SCOPES)
        if "user_code" not in flow:
            raise ConnectorError(str(flow.get("error_description", "Microsoft sign-in could not start")))
        return flow

    def complete(self, flow: dict[str, Any]) -> str:
        result = self.application.acquire_token_by_device_flow(flow)
        token = result.get("access_token")
        if not token:
            raise ConnectorError(str(result.get("error_description", "Microsoft sign-in failed")))
        return str(token)


class MicrosoftGraphConnector:
    def __init__(self, access_token: str, session: Any = requests) -> None:
        self.session = session
        self.headers = {"Authorization": f"Bearer {access_token}"}

    def _get_json(self, path: str, **kwargs: Any) -> dict[str, Any]:
        response = self.session.get(f"{GRAPH_ROOT}{path}", headers=self.headers, timeout=30, **kwargs)
        self._raise(response)
        return dict(response.json())

    @staticmethod
    def _raise(response: Any) -> None:
        if response.status_code >= 400:
            try:
                error = response.json().get("error", {})
                message = error.get("message") or response.text
            except ValueError:
                message = response.text
            raise ConnectorError(f"Microsoft Graph returned {response.status_code}: {message}")

    def search_files(self, query: str, site_id: str | None = None) -> list[RemoteTranscript]:
        escaped = quote(query.replace("'", "''"), safe="")
        root = f"/sites/{site_id}/drive" if site_id else "/me/drive"
        data = self._get_json(
            f"{root}/root/search(q='{escaped}')",
            params={"$top": 50, "$select": "id,name,lastModifiedDateTime,parentReference,remoteItem"},
        )
        items: list[RemoteTranscript] = []
        for item in data.get("value", []):
            name = str(item.get("name", ""))
            if not _supported_name(name):
                continue
            remote = item.get("remoteItem") or {}
            parent = remote.get("parentReference") or item.get("parentReference") or {}
            items.append(
                RemoteTranscript(
                    id=str(remote.get("id") or item["id"]),
                    name=name,
                    source=TranscriptSource.MICROSOFT_365,
                    modified_at=item.get("lastModifiedDateTime"),
                    detail="SharePoint" if site_id else "OneDrive",
                    metadata={"drive_id": parent.get("driveId")},
                )
            )
        return items

    def download_file(self, item: RemoteTranscript) -> TranscriptDocument:
        drive_id = item.metadata.get("drive_id")
        path = f"/drives/{drive_id}/items/{item.id}/content" if drive_id else f"/me/drive/items/{item.id}/content"
        response = self.session.get(f"{GRAPH_ROOT}{path}", headers=self.headers, timeout=30)
        self._raise(response)
        parsed = parse_uploaded_transcript(item.name, response.content, response.headers.get("Content-Type"))
        return _as_source(parsed, item.source, item.id)

    def recent_teams_meetings(self, days: int = 30) -> list[RemoteTranscript]:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days)
        data = self._get_json(
            "/me/calendarView",
            params={
                "startDateTime": start.isoformat(),
                "endDateTime": end.isoformat(),
                "$top": 50,
                "$select": "id,subject,start,end,isOnlineMeeting,onlineMeeting",
            },
        )
        meetings: list[RemoteTranscript] = []
        for event in data.get("value", []):
            join_url = (event.get("onlineMeeting") or {}).get("joinUrl")
            if event.get("isOnlineMeeting") and join_url:
                meetings.append(
                    RemoteTranscript(
                        id=str(event["id"]),
                        name=str(event.get("subject") or "Teams meeting"),
                        source=TranscriptSource.TEAMS,
                        modified_at=(event.get("start") or {}).get("dateTime"),
                        detail="Teams meeting",
                        metadata={"join_url": join_url},
                    )
                )
        return meetings

    def download_teams_transcript(self, meeting: RemoteTranscript) -> TranscriptDocument:
        join_url = str(meeting.metadata["join_url"]).replace("'", "''")
        resolved = self._get_json(
            "/me/onlineMeetings",
            params={"$filter": f"JoinWebUrl eq '{join_url}'"},
        ).get("value", [])
        if not resolved:
            raise ConnectorError("No online meeting was found for this calendar event")
        meeting_id = resolved[0]["id"]
        transcripts = self._get_json(f"/me/onlineMeetings/{meeting_id}/transcripts").get("value", [])
        if not transcripts:
            raise ConnectorError("This meeting has no available transcript")
        latest = max(transcripts, key=lambda item: item.get("createdDateTime", ""))
        transcript_id = latest["id"]
        response = self.session.get(
            f"{GRAPH_ROOT}/me/onlineMeetings/{meeting_id}/transcripts/{transcript_id}/content",
            headers={**self.headers, "Accept": "text/vtt"},
            timeout=30,
        )
        self._raise(response)
        parsed = parse_uploaded_transcript(f"{meeting.name}.vtt", response.content, "text/vtt")
        return _as_source(parsed, TranscriptSource.TEAMS, str(transcript_id))

    def recent_mail_attachments(self) -> list[RemoteTranscript]:
        data = self._get_json(
            "/me/messages",
            params={
                "$filter": "hasAttachments eq true",
                "$orderby": "receivedDateTime desc",
                "$top": 25,
                "$select": "id,subject,from,receivedDateTime",
            },
        )
        results: list[RemoteTranscript] = []
        for message in data.get("value", []):
            attachments = self._get_json(f"/me/messages/{message['id']}/attachments").get("value", [])
            for attachment in attachments:
                name = str(attachment.get("name", ""))
                if _supported_name(name):
                    sender = (((message.get("from") or {}).get("emailAddress") or {}).get("address") or "")
                    results.append(
                        RemoteTranscript(
                            id=str(attachment["id"]),
                            name=name,
                            source=TranscriptSource.EMAIL,
                            modified_at=message.get("receivedDateTime"),
                            detail=f"{message.get('subject', 'Email')} · {sender}",
                            metadata={"message_id": message["id"]},
                        )
                    )
        return results

    def download_mail_attachment(self, item: RemoteTranscript) -> TranscriptDocument:
        message_id = item.metadata["message_id"]
        response = self.session.get(
            f"{GRAPH_ROOT}/me/messages/{message_id}/attachments/{item.id}/$value",
            headers=self.headers,
            timeout=30,
        )
        self._raise(response)
        parsed = parse_uploaded_transcript(item.name, response.content, response.headers.get("Content-Type"))
        return _as_source(parsed, TranscriptSource.EMAIL, item.id)


class AzureBlobConnector:
    def __init__(self, account_url: str, container: str, credential: Any | None = None) -> None:
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import BlobServiceClient

        self.container = container
        self.client = BlobServiceClient(
            account_url=account_url,
            credential=credential or DefaultAzureCredential(exclude_interactive_browser_credential=True),
        ).get_container_client(container)

    def list_transcripts(self, prefix: str = "") -> list[RemoteTranscript]:
        return [
            RemoteTranscript(
                id=blob.name,
                name=Path(blob.name).name,
                source=TranscriptSource.AZURE_BLOB,
                modified_at=blob.last_modified.isoformat() if blob.last_modified else None,
                detail=self.container,
            )
            for blob in self.client.list_blobs(name_starts_with=prefix)
            if _supported_name(blob.name)
        ]

    def download(self, item: RemoteTranscript) -> TranscriptDocument:
        content = self.client.download_blob(item.id).readall()
        parsed = parse_uploaded_transcript(item.name, content)
        return _as_source(parsed, TranscriptSource.AZURE_BLOB, item.id)


def load_google_credentials(credentials_path: str, token_path: str):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    credentials = None
    if Path(token_path).exists():
        credentials = Credentials.from_authorized_user_file(token_path, GOOGLE_SCOPES)
    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
    if not credentials or not credentials.valid or not set(GOOGLE_SCOPES).issubset(credentials.scopes or []):
        flow = InstalledAppFlow.from_client_secrets_file(credentials_path, GOOGLE_SCOPES)
        credentials = flow.run_local_server(port=0)
    Path(token_path).write_text(credentials.to_json(), encoding="utf-8")
    return credentials


class GoogleWorkspaceConnector:
    def __init__(self, credentials: Any) -> None:
        from googleapiclient.discovery import build

        self.drive = build("drive", "v3", credentials=credentials)
        self.gmail = build("gmail", "v1", credentials=credentials)

    def search_drive(self, query: str) -> list[RemoteTranscript]:
        escaped = query.replace("'", "\\'")
        result = self.drive.files().list(
            q=f"trashed = false and name contains '{escaped}'",
            fields="files(id,name,mimeType,modifiedTime,webViewLink)",
            pageSize=50,
        ).execute()
        return [
            RemoteTranscript(
                id=item["id"],
                name=item["name"],
                source=TranscriptSource.GOOGLE_DRIVE,
                modified_at=item.get("modifiedTime"),
                detail="Google Drive",
                metadata={"mime_type": item.get("mimeType")},
            )
            for item in result.get("files", [])
            if _supported_name(item["name"]) or item.get("mimeType") == "application/vnd.google-apps.document"
        ]

    def download_drive(self, item: RemoteTranscript) -> TranscriptDocument:
        from googleapiclient.http import MediaIoBaseDownload

        output = __import__("io").BytesIO()
        if item.metadata.get("mime_type") == "application/vnd.google-apps.document":
            request = self.drive.files().export_media(fileId=item.id, mimeType="text/plain")
            filename = f"{item.name}.txt"
        else:
            request = self.drive.files().get_media(fileId=item.id)
            filename = item.name
        downloader = MediaIoBaseDownload(output, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        parsed = parse_uploaded_transcript(filename, output.getvalue())
        return _as_source(parsed, TranscriptSource.GOOGLE_DRIVE, item.id)

    def recent_gmail_attachments(self) -> list[RemoteTranscript]:
        messages = self.gmail.users().messages().list(
            userId="me", q="has:attachment newer_than:30d", maxResults=25
        ).execute()
        results: list[RemoteTranscript] = []
        for reference in messages.get("messages", []):
            message = self.gmail.users().messages().get(userId="me", id=reference["id"]).execute()
            headers = {item["name"].lower(): item["value"] for item in message["payload"].get("headers", [])}
            for part in _gmail_parts(message["payload"]):
                name = str(part.get("filename", ""))
                attachment_id = (part.get("body") or {}).get("attachmentId")
                if attachment_id and _supported_name(name):
                    results.append(
                        RemoteTranscript(
                            id=attachment_id,
                            name=name,
                            source=TranscriptSource.EMAIL,
                            detail=f"{headers.get('subject', 'Email')} · {headers.get('from', '')}",
                            metadata={"message_id": reference["id"]},
                        )
                    )
        return results

    def download_gmail_attachment(self, item: RemoteTranscript) -> TranscriptDocument:
        result = self.gmail.users().messages().attachments().get(
            userId="me", messageId=item.metadata["message_id"], id=item.id
        ).execute()
        content = base64.urlsafe_b64decode(result["data"] + "===")
        parsed = parse_uploaded_transcript(item.name, content)
        return _as_source(parsed, TranscriptSource.EMAIL, item.id)


def _gmail_parts(part: dict[str, Any]):
    yield part
    for child in part.get("parts", []):
        yield from _gmail_parts(child)


class ZoomConnector:
    def __init__(
        self,
        account_id: str,
        client_id: str,
        client_secret: str,
        user_id: str,
        session: Any = requests,
    ) -> None:
        self.session = session
        response = session.post(
            "https://zoom.us/oauth/token",
            params={"grant_type": "account_credentials", "account_id": account_id},
            auth=(client_id, client_secret),
            timeout=30,
        )
        if response.status_code >= 400:
            raise ConnectorError(f"Zoom authentication failed: {response.text}")
        self.headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
        self.user_id = user_id

    @classmethod
    def from_environment(cls) -> "ZoomConnector":
        required = ["ZOOM_ACCOUNT_ID", "ZOOM_CLIENT_ID", "ZOOM_CLIENT_SECRET", "ZOOM_USER_ID"]
        missing = [name for name in required if not os.getenv(name)]
        if missing:
            raise ConnectorError("Missing Zoom configuration: " + ", ".join(missing))
        return cls(*(os.environ[name] for name in required))

    def list_transcripts(self) -> list[RemoteTranscript]:
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=30)
        response = self.session.get(
            f"https://api.zoom.us/v2/users/{quote(self.user_id, safe='')}/recordings",
            headers=self.headers,
            params={"from": start.isoformat(), "to": end.isoformat(), "page_size": 100},
            timeout=30,
        )
        if response.status_code >= 400:
            raise ConnectorError(f"Zoom returned {response.status_code}: {response.text}")
        results: list[RemoteTranscript] = []
        for meeting in response.json().get("meetings", []):
            for recording in meeting.get("recording_files", []):
                if recording.get("file_type") == "TRANSCRIPT" or recording.get("recording_type") == "audio_transcript":
                    results.append(
                        RemoteTranscript(
                            id=str(recording["id"]),
                            name=f"{meeting.get('topic', 'Zoom meeting')}.vtt",
                            source=TranscriptSource.ZOOM,
                            modified_at=recording.get("recording_end"),
                            detail="Zoom cloud recording",
                            metadata={"download_url": recording["download_url"]},
                        )
                    )
        return results

    def download(self, item: RemoteTranscript) -> TranscriptDocument:
        response = self.session.get(item.metadata["download_url"], headers=self.headers, timeout=30)
        if response.status_code >= 400:
            raise ConnectorError(f"Zoom transcript download failed: {response.text}")
        parsed = parse_uploaded_transcript(item.name, response.content, "text/vtt")
        return _as_source(parsed, TranscriptSource.ZOOM, item.id)