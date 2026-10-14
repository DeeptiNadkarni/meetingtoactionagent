from meeting_to_action.models import ActionItem, Evidence
from meeting_to_action.workflows import ActionWorkflowDraft


def test_workflow_preview_carries_grounded_action_to_outlook_and_teams() -> None:
    draft = ActionWorkflowDraft(
        meeting_title="Launch review",
        action=ActionItem(
            id="A1",
            task="Prepare the launch brief",
            owner="Maya",
            deadline_text="Friday",
            evidence=[Evidence(quote="Maya will prepare the brief by Friday.", line_start=4, line_end=4)],
        ),
        recipients=["maya@example.com"],
    )

    assert draft.graph_message()["toRecipients"][0]["emailAddress"]["address"] == "maya@example.com"
    assert draft.outlook_url().startswith("https://outlook.office.com/mail/deeplink/compose?")
    assert draft.teams_url().startswith("https://teams.microsoft.com/l/chat/0/0?")
    assert draft.adaptive_card()["type"] == "AdaptiveCard"