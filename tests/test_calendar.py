from datetime import datetime, timedelta

import pytest

from meeting_to_action.calendar import CalendarEventDraft, CalendarProvider, create_calendar_event


def make_draft() -> CalendarEventDraft:
    start = datetime.fromisoformat("2026-09-25T09:00:00")
    return CalendarEventDraft(
        summary="Publish the report",
        start=start,
        end=start + timedelta(minutes=30),
        timezone="America/Los_Angeles",
    )


def test_calendar_body_is_previewable() -> None:
    body = make_draft().google_body()

    assert body["summary"] == "Publish the report"
    assert body["start"]["timeZone"] == "America/Los_Angeles"


def test_calendar_write_requires_explicit_approval() -> None:
    with pytest.raises(PermissionError, match="explicit approval"):
        create_calendar_event(
            make_draft(),
            approved=False,
            credentials_path="credentials.json",
            token_path="token.json",
        )


def test_outlook_draft_contains_event_and_attendees() -> None:
    draft = make_draft().model_copy(update={"attendees": ["owner@example.com"]})

    url = draft.provider_url(CalendarProvider.OUTLOOK)

    assert url.startswith("https://outlook.office.com/calendar/0/deeplink/compose?")
    assert "subject=Publish+the+report" in url
    assert "requiredattendees=owner%40example.com" in url


def test_yahoo_draft_contains_event_times() -> None:
    url = make_draft().provider_url(CalendarProvider.YAHOO)

    assert url.startswith("https://calendar.yahoo.com/?")
    assert "st=20260925T090000" in url
    assert "et=20260925T093000" in url


def test_icalendar_download_uses_utc_and_escapes_text() -> None:
    draft = make_draft().model_copy(
        update={"description": "Meeting notes, line one\nline two"}
    )

    calendar = draft.icalendar().decode("utf-8")

    assert "DTSTART:20260925T160000Z" in calendar
    assert "DESCRIPTION:Meeting notes\\, line one\\nline two" in calendar
    assert calendar.endswith("END:VCALENDAR\r\n")