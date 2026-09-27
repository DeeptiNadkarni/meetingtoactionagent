"""Calendar event previews and approval-gated provider integrations."""

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, model_validator

CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events"


class CalendarProvider(StrEnum):
    GOOGLE = "Google Calendar"
    OUTLOOK = "Outlook / Microsoft 365"
    YAHOO = "Yahoo Calendar"
    ICALENDAR = "Apple / other (.ics)"


class CalendarEventDraft(BaseModel):
    summary: str = Field(min_length=1)
    start: datetime
    end: datetime
    timezone: str = Field(min_length=1)
    description: str = ""
    attendees: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def end_must_follow_start(self) -> "CalendarEventDraft":
        if self.end <= self.start:
            raise ValueError("Event end must be after its start")
        return self

    def google_body(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "summary": self.summary,
            "description": self.description,
            "start": {"dateTime": self.start.isoformat(), "timeZone": self.timezone},
            "end": {"dateTime": self.end.isoformat(), "timeZone": self.timezone},
        }
        if self.attendees:
            body["attendees"] = [{"email": email} for email in self.attendees]
        return body

    def provider_url(self, provider: CalendarProvider) -> str:
        if provider is CalendarProvider.OUTLOOK:
            query = {
                "path": "/calendar/action/compose",
                "rru": "addevent",
                "subject": self.summary,
                "startdt": self.start.isoformat(),
                "enddt": self.end.isoformat(),
                "body": self.description,
            }
            if self.attendees:
                query["requiredattendees"] = ";".join(self.attendees)
            return "https://outlook.office.com/calendar/0/deeplink/compose?" + urlencode(query)
        if provider is CalendarProvider.YAHOO:
            query = {
                "v": "60",
                "title": self.summary,
                "st": self.start.strftime("%Y%m%dT%H%M%S"),
                "et": self.end.strftime("%Y%m%dT%H%M%S"),
                "desc": self.description,
            }
            return "https://calendar.yahoo.com/?" + urlencode(query)
        raise ValueError(f"{provider.value} does not use a provider draft URL")

    def icalendar(self) -> bytes:
        timezone = ZoneInfo(self.timezone)
        start_utc = self.start.replace(tzinfo=timezone).astimezone(ZoneInfo("UTC"))
        end_utc = self.end.replace(tzinfo=timezone).astimezone(ZoneInfo("UTC"))
        identity = "|".join((self.summary, self.start.isoformat(), self.end.isoformat()))
        uid = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//Meeting to Action//EN",
            "CALSCALE:GREGORIAN",
            "METHOD:PUBLISH",
            "BEGIN:VEVENT",
            f"UID:{uid}@meeting-to-action.local",
            f"DTSTART:{start_utc.strftime('%Y%m%dT%H%M%SZ')}",
            f"DTEND:{end_utc.strftime('%Y%m%dT%H%M%SZ')}",
            f"SUMMARY:{_ical_escape(self.summary)}",
            f"DESCRIPTION:{_ical_escape(self.description)}",
            *(f"ATTENDEE:MAILTO:{email}" for email in self.attendees),
            "END:VEVENT",
            "END:VCALENDAR",
        ]
        return ("\r\n".join(lines) + "\r\n").encode("utf-8")


def _ical_escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def _load_credentials(credentials_path: Path, token_path: Path):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    credentials = None
    if token_path.exists():
        credentials = Credentials.from_authorized_user_file(token_path, [CALENDAR_SCOPE])
    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
    if not credentials or not credentials.valid:
        flow = InstalledAppFlow.from_client_secrets_file(credentials_path, [CALENDAR_SCOPE])
        credentials = flow.run_local_server(port=0)
    token_path.write_text(credentials.to_json(), encoding="utf-8")
    return credentials


def create_calendar_event(
    draft: CalendarEventDraft,
    *,
    approved: bool,
    credentials_path: str | Path,
    token_path: str | Path,
    calendar_id: str = "primary",
) -> dict[str, Any]:
    if not approved:
        raise PermissionError("Calendar event creation requires explicit approval")

    from googleapiclient.discovery import build

    credentials = _load_credentials(Path(credentials_path), Path(token_path))
    service = build("calendar", "v3", credentials=credentials)
    event = service.events().insert(
        calendarId=calendar_id,
        body=draft.google_body(),
        sendUpdates="all" if draft.attendees else "none",
    ).execute()
    return json.loads(json.dumps(event))