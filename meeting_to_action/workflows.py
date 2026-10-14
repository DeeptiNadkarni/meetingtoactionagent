"""Approval-preview payloads for Outlook and Microsoft Teams."""

from urllib.parse import urlencode

from pydantic import BaseModel, Field

from meeting_to_action.models import ActionItem


class ActionWorkflowDraft(BaseModel):
    meeting_title: str = Field(min_length=1)
    action: ActionItem
    recipients: list[str] = Field(default_factory=list)

    @property
    def subject(self) -> str:
        return f"Meeting follow-up: {self.action.task}"

    @property
    def body(self) -> str:
        details = [
            f"Meeting: {self.meeting_title}",
            f"Action: {self.action.task}",
            f"Owner: {self.action.owner or 'Needs assignment'}",
            f"Deadline: {self.action.deadline_text or 'Needs confirmation'}",
            "",
            "Transcript evidence:",
            *[f"- {evidence.quote}" for evidence in self.action.evidence],
        ]
        return "\n".join(details)

    def graph_message(self) -> dict:
        message = {
            "subject": self.subject,
            "body": {"contentType": "Text", "content": self.body},
            "toRecipients": [
                {"emailAddress": {"address": recipient}}
                for recipient in self.recipients
            ],
        }
        return message

    def outlook_url(self) -> str:
        return "https://outlook.office.com/mail/deeplink/compose?" + urlencode({
            "to": ";".join(self.recipients),
            "subject": self.subject,
            "body": self.body,
        })

    def teams_url(self) -> str:
        return "https://teams.microsoft.com/l/chat/0/0?" + urlencode({
            "users": ",".join(self.recipients),
            "message": self.body,
        })

    def adaptive_card(self) -> dict:
        facts = [
            {"title": "Owner", "value": self.action.owner or "Needs assignment"},
            {"title": "Deadline", "value": self.action.deadline_text or "Needs confirmation"},
            {"title": "Evidence", "value": "\n".join(item.quote for item in self.action.evidence)},
        ]
        return {
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "type": "AdaptiveCard",
            "version": "1.5",
            "body": [
                {"type": "TextBlock", "text": self.action.task, "weight": "Bolder", "wrap": True},
                {"type": "FactSet", "facts": facts},
            ],
        }