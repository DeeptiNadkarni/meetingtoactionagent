"""Streamlit interface for meeting extraction, review, chat, and calendar actions."""

import asyncio
import html
import os
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv

from meeting_to_action.calendar import CalendarEventDraft, CalendarProvider, create_calendar_event
from meeting_to_action.chat import answer_question
from meeting_to_action.connectors import (
    AzureBlobConnector,
    ConnectorError,
    GoogleWorkspaceConnector,
    MicrosoftDeviceAuth,
    MicrosoftGraphConnector,
    RemoteTranscript,
    ZoomConnector,
    load_google_credentials,
)
from meeting_to_action.extraction import ExtractionStrategy, extract_meeting, foundry_is_configured
from meeting_to_action.ingestion import TranscriptDocument, parse_uploaded_transcript
from meeting_to_action.models import MeetingExtraction
from meeting_to_action.review import apply_review_edits, build_change_audit
from meeting_to_action.transcript import NumberedTranscript

load_dotenv()

SAMPLE_TRANSCRIPT = """Maya: We need the launch brief ready before the customer review.
Decision: We will launch the pilot to the west region first.
Action: Maya will prepare the launch brief by September 25.
Open question: Do we need legal approval for the pilot invitation?
Jon: I will ask legal and report back on Thursday."""

st.set_page_config(page_title="Meeting to Action", page_icon="✓", layout="wide")
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap');
    :root {
        --ink: #17332f;
        --teal: #087f73;
        --teal-light: #52aaa1;
        --paper: #fbfcfb;
        --app-font: 'DM Sans', 'Segoe UI', sans-serif;
    }
    .stApp {
        font-family: var(--app-font);
        font-size: 15px;
        line-height: 1.5;
        background-color: var(--paper);
        background-image: linear-gradient(rgba(8, 127, 115, .025) 1px, transparent 1px),
                          linear-gradient(90deg, rgba(8, 127, 115, .025) 1px, transparent 1px);
        background-size: 32px 32px;
    }
    .stApp p,
    .stApp label,
    .stApp input,
    .stApp textarea,
    .stApp button,
    .stApp [role="tab"],
    .stApp [role="option"],
    .stApp [data-baseweb="select"] {
        font-family: var(--app-font) !important;
        letter-spacing: 0 !important;
    }
    .stApp p { font-size: .9375rem; line-height: 1.5; }
    .block-container { max-width: 1500px; padding-top: 1rem; padding-bottom: 2rem; }
    h1, h2, h3 {
        color: var(--ink);
        font-family: var(--app-font) !important;
        font-weight: 700 !important;
        letter-spacing: 0 !important;
    }
    h2 { font-size: 1.125rem !important; line-height: 1.35 !important; }
    h3 { font-size: 1.5rem !important; line-height: 1.3 !important; }
    [data-testid="stHeader"] { background: rgba(251, 252, 251, .92); }
    .product-header { border-bottom: 2px solid #0b7167; margin-bottom: 1rem; padding: .15rem 0 .7rem; }
    h1.product-name {
        color: var(--teal) !important;
        font-family: var(--app-font) !important;
        font-size: 2.75rem;
        font-weight: 700 !important;
        letter-spacing: 0;
        line-height: 1.05;
        margin: 0;
        text-wrap: balance;
    }
    h1.product-name span { color: inherit; font-weight: inherit; }
    .product-tagline { color: #50635f; font-size: .875rem; font-weight: 600; line-height: 1.4; margin-top: .45rem; }
    [data-testid="stMetric"] { border-top: 3px solid var(--teal); padding-top: .65rem; }
    .st-key-extraction_metrics {
        background: #e9f5f2;
        border: 1px solid #c9e2dc;
        border-radius: 6px;
        margin-bottom: .65rem;
        padding: .65rem .85rem .55rem;
    }
    .summary-label { color: var(--ink); font-size: .875rem; font-weight: 700; }
    .st-key-extraction_metrics div.stButton > button {
        background: transparent;
        border: 0;
        box-shadow: none;
        color: var(--ink);
        justify-content: flex-start;
        min-height: 2.5rem;
        padding: 0 .25rem;
    }
    .st-key-extraction_metrics div.stButton > button:hover { background: rgba(8, 127, 115, .08); }
    .st-key-extraction_metrics div.stButton > button p { font-size: 1.75rem; font-weight: 600; line-height: 1; }
    [data-testid="stMetricLabel"] p,
    [data-testid="stExpander"] summary p,
    .stTabs [data-baseweb="tab"] p { color: var(--ink); font-weight: 700 !important; }
    .stTabs [data-baseweb="tab-list"] { border-bottom: 1px solid #cad5d2; gap: .35rem; }
    .stTabs [aria-selected="true"] {
        color: var(--teal) !important;
    }
    .stTabs [aria-selected="true"] p { color: var(--teal) !important; }
    .stTabs [role="tab"]:hover,
    .stTabs [role="tab"]:hover p { color: var(--teal) !important; }
    .stTabs [aria-selected="true"] .react-aria-SelectionIndicator {
        background-color: var(--teal-light) !important;
        color: var(--teal-light) !important;
    }
    [data-testid="stVerticalBlockBorderWrapper"] { background: rgba(255, 255, 255, .7); }
    .evidence { border-left: 3px solid var(--teal-light); padding: .25rem .75rem; margin: .4rem 0 1rem; }
    .transcript-lines { max-height: 26rem; overflow-y: auto; border: 1px solid #d9dfdd; }
    .transcript-line { display: grid; grid-template-columns: 3.5rem 1fr; gap: .75rem; padding: .35rem .75rem; }
    .transcript-line:nth-child(even) { background: #f6f8f7; }
    .transcript-line.selected { background: #e1f3f0; border-left: 4px solid var(--teal-light); padding-left: calc(.75rem - 4px); }
    .line-number { color: #58706c; font-variant-numeric: tabular-nums; text-align: right; user-select: none; }
    div.stButton > button[kind="primary"] { background: var(--teal); border-color: var(--teal); }
    @media (max-width: 640px) {
        h1.product-name { font-size: 2.25rem; }
        h3 { font-size: 1.375rem !important; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def editable_rows(items: list[Any], fields: tuple[str, ...]) -> list[dict[str, Any]]:
    return [{field: getattr(item, field) for field in fields} for item in items]


def clean_rows(frame: pd.DataFrame | list[dict[str, Any]]) -> list[dict[str, Any]]:
    records = frame.to_dict(orient="records") if isinstance(frame, pd.DataFrame) else frame
    return [
        {key: None if pd.isna(value) else value for key, value in row.items()}
        for row in records
    ]


def request_review_tab(tab_name: str) -> None:
    st.session_state.requested_review_tab = tab_name


def select_evidence_range(line_start: int, line_end: int) -> None:
    st.session_state.highlighted_lines = (line_start, line_end)
    st.session_state.scroll_to_transcript = True


def show_numbered_transcript(transcript_text: str) -> None:
    transcript = NumberedTranscript.from_text(transcript_text)
    selected = st.session_state.get("highlighted_lines")
    rows = []
    for line_number, line in enumerate(transcript.lines, 1):
        is_selected = selected and selected[0] <= line_number <= selected[1]
        selected_class = " selected" if is_selected else ""
        rows.append(
            f'<div class="transcript-line{selected_class}" id="transcript-line-{line_number}">'
            f'<span class="line-number">{line_number}</span>'
            f'<span>{html.escape(line)}</span></div>'
        )
    st.markdown('<div id="numbered-transcript-anchor"></div>', unsafe_allow_html=True)
    with st.expander("Numbered transcript", expanded=bool(selected)):
        if selected:
            st.caption(f"Highlighted evidence: lines {selected[0]}–{selected[1]}")
        st.markdown(
            f'<div class="transcript-lines">{"".join(rows)}</div>',
            unsafe_allow_html=True,
        )
    if st.session_state.pop("scroll_to_transcript", False):
        components.html(
            """
            <script>
            const target = window.parent.document.getElementById("numbered-transcript-anchor");
            if (target) {
                target.scrollIntoView({ behavior: "smooth", block: "start" });
            }
            </script>
            """,
            height=0,
        )


def show_evidence(extraction: MeetingExtraction) -> None:
    records = [
        *extraction.notes,
        *extraction.actions,
        *extraction.decisions,
        *extraction.open_questions,
    ]
    if not records:
        st.caption("No grounded records were extracted.")
        return
    for record in records:
        label = next(
            (getattr(record, field) for field in ("title", "task", "summary", "question") if hasattr(record, field)),
            record.id,
        )
        with st.expander(f"{record.id} · {label}"):
            for index, evidence in enumerate(record.evidence):
                reference, quote = st.columns([1, 4], vertical_alignment="top")
                reference.button(
                    f"Lines {evidence.line_start}–{evidence.line_end}",
                    key=f"evidence_lines_{record.id}_{index}",
                    on_click=select_evidence_range,
                    args=(evidence.line_start, evidence.line_end),
                    width="stretch",
                )
                quote.markdown(
                    f'<div class="evidence">“{html.escape(evidence.quote)}”</div>',
                    unsafe_allow_html=True,
                )


def show_change_audit() -> None:
    changes = st.session_state.get("review_audit")
    if changes is None:
        st.info("Approve the reviewed record to create a change audit.")
        return

    approved_at = st.session_state.get("review_approved_at")
    if approved_at:
        change_label = (
            f"{len(changes)} approved change"
            if len(changes) == 1
            else f"{len(changes)} approved changes"
        )
        st.caption(f"{change_label} · Last approved {approved_at}")
    if not changes:
        st.success("Approved without changes to the AI extraction.")
        return

    rows = [
        {
            "Record": change["record_type"],
            "ID": change["record_id"],
            "Field": change["field"].replace("_", " ").title(),
            "AI extraction": "Not set" if change["before"] is None else str(change["before"]),
            "Approved value": "Not set" if change["after"] is None else str(change["after"]),
        }
        for change in changes
    ]
    frame = pd.DataFrame(rows)
    st.dataframe(
        frame,
        hide_index=True,
        width="stretch",
        column_config={
            "Record": st.column_config.TextColumn(
                "Record", help="Type of reviewed meeting record that changed."
            ),
            "ID": st.column_config.TextColumn(
                "ID", help="Stable identifier of the changed record."
            ),
            "Field": st.column_config.TextColumn(
                "Field", help="Specific field changed during human review."
            ),
            "AI extraction": st.column_config.TextColumn(
                "AI extraction", help="Original value produced by extraction.", width="large"
            ),
            "Approved value": st.column_config.TextColumn(
                "Approved value", help="Final value accepted by the reviewer.", width="large"
            ),
        },
    )
    st.download_button(
        "Download change audit",
        data=frame.to_csv(index=False),
        file_name="meeting-change-audit.csv",
        mime="text/csv",
        width="stretch",
    )


def review_editor(extraction: MeetingExtraction) -> None:
    st.subheader("Human review")
    st.caption(extraction.summary)

    with st.expander("Meeting notes", expanded=True):
        if extraction.notes:
            note_columns = st.columns(min(len(extraction.notes), 3))
            for index, note in enumerate(extraction.notes):
                with note_columns[index % len(note_columns)]:
                    st.markdown(f"**{note.title}**")
                    st.caption(note.description)
            edit_notes = st.toggle(
                "Edit notes",
                key="edit_notes",
                help="Turn on editing for the extracted meeting-note sections below.",
            )
        else:
            st.caption("No meeting-note sections were extracted.")
            edit_notes = False

        if edit_notes:
            note_frame = st.data_editor(
                editable_rows(extraction.notes, ("id", "title", "description")),
                disabled=["id"],
                hide_index=True,
                width="stretch",
                num_rows="fixed",
                key="note_editor",
                column_config={
                    "id": st.column_config.TextColumn(
                        "ID", help="Stable identifier for this note section; it cannot be edited."
                    ),
                    "title": st.column_config.TextColumn(
                        "Section", help="Short topic name describing this part of the meeting."
                    ),
                    "description": st.column_config.TextColumn(
                        "Brief description",
                        help="Concise summary of what was discussed about this topic.",
                        width="large",
                    ),
                },
            )
        else:
            note_frame = editable_rows(extraction.notes, ("id", "title", "description"))

    actions_tab, decisions_tab, questions_tab, evidence_tab, audit_tab = st.tabs(
        [
            f"Actions ({len(extraction.actions)})",
            f"Decisions ({len(extraction.decisions)})",
            f"Open questions ({len(extraction.open_questions)})",
            "Evidence",
            "Change audit",
        ]
    )
    with actions_tab:
        action_frame = st.data_editor(
            editable_rows(extraction.actions, ("id", "task", "owner", "deadline_text", "deadline", "status")),
            disabled=["id"],
            hide_index=True,
            width="stretch",
            num_rows="fixed",
            column_config={
                "id": st.column_config.TextColumn(
                    "ID", help="Stable identifier for this action; it cannot be edited."
                ),
                "task": st.column_config.TextColumn(
                    "Task", help="The specific follow-up work agreed in the meeting."
                ),
                "owner": st.column_config.TextColumn(
                    "Owner", help="Person explicitly responsible for completing the action."
                ),
                "deadline_text": st.column_config.TextColumn(
                    "Deadline text",
                    help="Deadline exactly as spoken, such as 'Friday' or 'September 25'.",
                ),
                "deadline": st.column_config.DateColumn(
                    "Deadline",
                    help="Calendar date only when the meeting stated enough information to resolve it.",
                ),
                "status": st.column_config.SelectboxColumn(
                    "Status",
                    help="Current state of the action: proposed, confirmed, or completed.",
                    options=["proposed", "confirmed", "completed"],
                ),
            },
            key="action_editor",
        )
    with decisions_tab:
        decision_frame = st.data_editor(
            editable_rows(extraction.decisions, ("id", "summary", "rationale")),
            disabled=["id"],
            hide_index=True,
            width="stretch",
            num_rows="fixed",
            column_config={
                "id": st.column_config.TextColumn(
                    "ID", help="Stable identifier for this decision; it cannot be edited."
                ),
                "summary": st.column_config.TextColumn(
                    "Summary", help="Concise statement of what the group decided."
                ),
                "rationale": st.column_config.TextColumn(
                    "Rationale", help="Reason given in the meeting for making this decision."
                ),
            },
            key="decision_editor",
        )
    with questions_tab:
        question_frame = st.data_editor(
            editable_rows(extraction.open_questions, ("id", "question", "owner")),
            disabled=["id"],
            hide_index=True,
            width="stretch",
            num_rows="fixed",
            column_config={
                "id": st.column_config.TextColumn(
                    "ID", help="Stable identifier for this question; it cannot be edited."
                ),
                "question": st.column_config.TextColumn(
                    "Question", help="Issue raised in the meeting that remains unresolved."
                ),
                "owner": st.column_config.TextColumn(
                    "Owner", help="Person explicitly assigned to resolve or follow up on the question."
                ),
            },
            key="question_editor",
        )
    with evidence_tab:
        show_evidence(extraction)

    if st.button("Approve reviewed record", type="primary", width="stretch"):
        try:
            reviewed = apply_review_edits(
                extraction,
                clean_rows(action_frame),
                clean_rows(decision_frame),
                clean_rows(question_frame),
                clean_rows(note_frame),
            )
            st.session_state.reviewed = reviewed
            st.session_state.review_audit = build_change_audit(extraction, reviewed)
            st.session_state.review_approved_at = datetime.now().astimezone().strftime(
                "%Y-%m-%d %H:%M:%S %Z"
            )
            st.success("Reviewed record approved.")
        except (KeyError, ValueError) as error:
            st.error(f"Review could not be saved: {error}")

    with audit_tab:
        show_change_audit()

    requested_tab = st.session_state.pop("requested_review_tab", None)
    if requested_tab:
        components.html(
            f"""
            <script>
            const doc = window.parent.document;
            const reviewTab = [...doc.querySelectorAll('[role="tab"]')]
                .find(tab => tab.textContent.trim() === 'Review');
            if (reviewTab) reviewTab.click();
            setTimeout(() => {{
                const target = [...doc.querySelectorAll('[role="tab"]')]
                    .find(tab => tab.textContent.trim().startsWith('{requested_tab}'));
                if (target) {{
                    target.click();
                    target.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
                }}
            }}, 100);
            </script>
            """,
            height=0,
        )

def chat_panel(transcript_text: str, reviewed: MeetingExtraction) -> None:
    st.subheader(
        "Ask this meeting",
        help=(
            "Ask factual or analytical questions about this meeting. Answers use the transcript "
            "and reviewed record as their evidence sources."
        ),
    )
    for message in st.session_state.setdefault("messages", []):
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    question = st.chat_input("Ask about an action, decision, owner, or deadline")
    if question:
        st.session_state.messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant"):
            try:
                with st.spinner("Checking the meeting record…"):
                    answer = asyncio.run(
                        answer_question(
                            question,
                            NumberedTranscript.from_text(transcript_text),
                            reviewed,
                        )
                    )
                citation_text = " ".join(
                    f"[Lines {citation.line_start}–{citation.line_end}]"
                    for citation in answer.citations
                )
                content = f"{answer.answer}  \n{citation_text}" if citation_text else answer.answer
            except Exception as error:
                content = f"The answer could not be grounded: {error}"
            st.markdown(content)
        st.session_state.messages.append({"role": "assistant", "content": content})


def calendar_panel(reviewed: MeetingExtraction) -> None:
    st.subheader("Calendar preview")
    if not reviewed.actions:
        st.info("Approve at least one action before preparing an event.")
        return

    selected_id = st.selectbox(
        "Action",
        [item.id for item in reviewed.actions],
        help="Choose the approved action that this calendar event will track.",
        format_func=lambda item_id: next(
            item.task for item in reviewed.actions if item.id == item_id
        ),
    )
    action = next(item for item in reviewed.actions if item.id == selected_id)
    provider = st.selectbox(
        "Calendar provider",
        list(CalendarProvider),
        help="Choose where to create, open, or download the event.",
        format_func=lambda item: item.value,
    )
    default_date = action.deadline or date.today() + timedelta(days=1)
    left, right = st.columns(2)
    event_date = left.date_input(
        "Date", value=default_date, help="Date when the follow-up event should occur."
    )
    event_time = right.time_input(
        "Start", value=time(9, 0), help="Local start time in the selected time zone."
    )
    duration = st.select_slider(
        "Duration",
        options=[15, 30, 45, 60, 90],
        value=30,
        help="Length of the calendar event in minutes.",
        format_func=lambda x: f"{x} min",
    )
    timezone = st.selectbox(
        "Time zone",
        ["America/Los_Angeles", "America/Denver", "America/Chicago", "America/New_York", "UTC"],
        help="Time zone used to interpret the event date and start time.",
    )
    attendees = st.text_input(
        "Attendees",
        placeholder="name@example.com, owner@example.com",
        help="Optional comma-separated email addresses to invite.",
    )
    start = datetime.combine(event_date, event_time)
    draft = CalendarEventDraft(
        summary=action.task,
        start=start,
        end=start + timedelta(minutes=duration),
        timezone=timezone,
        description="\n".join(
            [f"Meeting: {reviewed.title}", *[f"Evidence: {item.quote}" for item in action.evidence]]
        ),
        attendees=[email.strip() for email in attendees.split(",") if email.strip()],
    )

    st.json(draft.google_body(), expanded=True)
    approved = st.checkbox(
        f"I reviewed this event for {provider.value}",
        help="Confirm the event details before creation, opening, or download is enabled.",
    )
    if provider is CalendarProvider.GOOGLE:
        credentials_path = st.text_input(
            "Google OAuth client file",
            value="credentials.json",
            help="Path to the Google OAuth desktop-client credentials JSON file.",
        )
        if st.button("Create event", type="primary", disabled=not approved, width="stretch"):
            try:
                with st.spinner("Creating calendar event…"):
                    event = create_calendar_event(
                        draft,
                        approved=approved,
                        credentials_path=credentials_path,
                        token_path=Path("token.json"),
                    )
                st.success("Calendar event created.")
                if event.get("htmlLink"):
                    st.link_button("Open in Google Calendar", event["htmlLink"], width="stretch")
            except Exception as error:
                st.error(f"Calendar event was not created: {error}")
    elif provider in (CalendarProvider.OUTLOOK, CalendarProvider.YAHOO):
        st.link_button(
            f"Open draft in {provider.value}",
            draft.provider_url(provider),
            type="primary",
            disabled=not approved,
            width="stretch",
        )
    else:
        st.download_button(
            "Download calendar event",
            data=draft.icalendar(),
            file_name="meeting-action.ics",
            mime="text/calendar",
            type="primary",
            disabled=not approved,
            width="stretch",
        )


def import_document(document: TranscriptDocument) -> None:
    previous_hash = st.session_state.get("transcript_hash")
    st.session_state.transcript_input = document.text
    st.session_state.meeting_title = document.title
    st.session_state.transcript_hash = document.content_hash
    st.session_state.imported_document = document.model_dump(mode="json")
    st.session_state.extraction = None
    st.session_state.reviewed = None
    st.session_state.review_audit = None
    st.session_state.review_approved_at = None
    st.session_state.messages = []
    st.session_state.highlighted_lines = None
    if previous_hash == document.content_hash:
        st.info("This transcript was already imported; the existing text was refreshed.")
    else:
        st.success(f"Imported {document.filename} from {document.source.value}.")


def candidate_picker(key: str, items: list[RemoteTranscript], download: Any) -> None:
    if not items:
        st.caption("No supported transcript files were found.")
        return
    selected_id = st.selectbox(
        "Transcript",
        [item.id for item in items],
        help="Choose the remote transcript or transcript attachment to import.",
        format_func=lambda item_id: next(
            f"{item.name} · {item.detail}" for item in items if item.id == item_id
        ),
        key=f"{key}_selected",
    )
    if st.button("Import selected", key=f"{key}_import", width="stretch"):
        selected = next(item for item in items if item.id == selected_id)
        try:
            with st.spinner("Importing transcript…"):
                import_document(download(selected))
        except Exception as error:
            st.error(f"Import failed: {error}")


def microsoft_sign_in() -> str | None:
    token = st.session_state.get("microsoft_access_token")
    if token:
        return str(token)
    client_id = os.getenv("MICROSOFT_CLIENT_ID")
    if not client_id:
        st.caption("Set MICROSOFT_CLIENT_ID to connect a work or school account.")
        return None
    auth = MicrosoftDeviceAuth(client_id, os.getenv("MICROSOFT_TENANT_ID", "organizations"))
    if st.button("Start Microsoft sign-in", width="stretch"):
        try:
            st.session_state.microsoft_device_flow = auth.start()
        except ConnectorError as error:
            st.error(error)
    flow = st.session_state.get("microsoft_device_flow")
    if flow:
        st.info(flow.get("message", "Open the verification URL and enter the displayed code."))
        if st.button("I completed sign-in", width="stretch"):
            try:
                st.session_state.microsoft_access_token = auth.complete(flow)
                st.session_state.pop("microsoft_device_flow", None)
                st.rerun()
            except ConnectorError as error:
                st.error(error)
    return None


def google_sign_in() -> Any | None:
    credentials = st.session_state.get("google_workspace_credentials")
    if credentials:
        return credentials
    credentials_path = os.getenv("GOOGLE_OAUTH_CREDENTIALS", "credentials.json")
    token_path = os.getenv("GOOGLE_WORKSPACE_TOKEN", ".google-workspace-token.json")
    if not Path(credentials_path).exists():
        st.caption(f"Add a Google OAuth desktop client file at {credentials_path}.")
        return None
    if st.button("Connect Google Workspace", width="stretch"):
        try:
            st.session_state.google_workspace_credentials = load_google_credentials(
                credentials_path, token_path
            )
            st.rerun()
        except Exception as error:
            st.error(f"Google sign-in failed: {error}")
    return None


def source_panel(source: str) -> None:
    if source == "Upload":
        uploaded = st.file_uploader(
            "Transcript file",
            type=["txt", "vtt", "srt", "docx", "eml"],
            help="Upload a TXT, VTT, SRT, DOCX, or EML meeting transcript (maximum 10 MB).",
            max_upload_size=10,
        )
        if uploaded and st.button("Import upload", width="stretch"):
            try:
                import_document(
                    parse_uploaded_transcript(uploaded.name, uploaded.getvalue(), uploaded.type)
                )
            except ValueError as error:
                st.error(error)
        return

    if source in {"Microsoft 365", "Teams", "Outlook email"}:
        token = microsoft_sign_in()
        if not token:
            return
        connector = MicrosoftGraphConnector(token)
        if source == "Microsoft 365":
            query = st.text_input(
                "Search files",
                value="transcript",
                help="Words to match when searching Microsoft 365 files.",
            )
            site_id = st.text_input(
                "SharePoint site ID",
                placeholder="Optional; leave blank for OneDrive",
                help="Optional Microsoft Graph site ID; leave blank to search OneDrive.",
            )
            if st.button("Search Microsoft 365", width="stretch"):
                try:
                    st.session_state.microsoft_files = connector.search_files(query, site_id or None)
                except ConnectorError as error:
                    st.error(error)
            candidate_picker(
                "microsoft_files", st.session_state.get("microsoft_files", []), connector.download_file
            )
        elif source == "Teams":
            if st.button("Find recent Teams meetings", width="stretch"):
                try:
                    st.session_state.teams_meetings = connector.recent_teams_meetings()
                except ConnectorError as error:
                    st.error(error)
            candidate_picker(
                "teams_meetings",
                st.session_state.get("teams_meetings", []),
                connector.download_teams_transcript,
            )
        else:
            if st.button("Find Outlook attachments", width="stretch"):
                try:
                    st.session_state.outlook_attachments = connector.recent_mail_attachments()
                except ConnectorError as error:
                    st.error(error)
            candidate_picker(
                "outlook_attachments",
                st.session_state.get("outlook_attachments", []),
                connector.download_mail_attachment,
            )
        return

    if source == "Azure Blob":
        account_url = os.getenv("AZURE_STORAGE_ACCOUNT_URL")
        container = os.getenv("AZURE_STORAGE_CONTAINER")
        if not account_url or not container:
            st.caption("Set AZURE_STORAGE_ACCOUNT_URL and AZURE_STORAGE_CONTAINER.")
            return
        prefix = st.text_input(
            "Blob prefix",
            value=os.getenv("AZURE_STORAGE_PREFIX", ""),
            help="Optional virtual folder or name prefix used to filter transcript blobs.",
        )
        connector = AzureBlobConnector(account_url, container)
        if st.button("List blob transcripts", width="stretch"):
            try:
                st.session_state.blob_files = connector.list_transcripts(prefix)
            except Exception as error:
                st.error(f"Azure Blob listing failed: {error}")
        candidate_picker("blob_files", st.session_state.get("blob_files", []), connector.download)
        return

    if source in {"Google Drive", "Gmail"}:
        credentials = google_sign_in()
        if not credentials:
            return
        connector = GoogleWorkspaceConnector(credentials)
        if source == "Google Drive":
            query = st.text_input(
                "Search Drive",
                value="transcript",
                help="Words to match when searching Google Drive files.",
            )
            if st.button("Search Google Drive", width="stretch"):
                try:
                    st.session_state.drive_files = connector.search_drive(query)
                except Exception as error:
                    st.error(f"Google Drive search failed: {error}")
            candidate_picker(
                "drive_files", st.session_state.get("drive_files", []), connector.download_drive
            )
        else:
            if st.button("Find Gmail attachments", width="stretch"):
                try:
                    st.session_state.gmail_attachments = connector.recent_gmail_attachments()
                except Exception as error:
                    st.error(f"Gmail search failed: {error}")
            candidate_picker(
                "gmail_attachments",
                st.session_state.get("gmail_attachments", []),
                connector.download_gmail_attachment,
            )
        return

    if source == "Zoom":
        if not all(os.getenv(name) for name in (
            "ZOOM_ACCOUNT_ID", "ZOOM_CLIENT_ID", "ZOOM_CLIENT_SECRET", "ZOOM_USER_ID"
        )):
            st.caption("Set the four ZOOM_* variables to connect cloud recordings.")
            return
        if st.button("Find Zoom transcripts", width="stretch"):
            try:
                connector = ZoomConnector.from_environment()
                st.session_state.zoom_files = connector.list_transcripts()
            except ConnectorError as error:
                st.error(error)
        items = st.session_state.get("zoom_files", [])
        if items:
            candidate_picker("zoom_files", items, ZoomConnector.from_environment().download)


st.markdown(
    """
    <header class="product-header">
        <h1
            class="product-name"
            title="Turn meeting transcripts into grounded notes, actions, decisions, answers, and calendar follow-ups."
            aria-label="Meeting To Action: Turn meeting transcripts into grounded notes, actions, decisions, answers, and calendar follow-ups."
        >Meeting <span>To</span> Action</h1>
        <div class="product-tagline">Extract · Verify · Review · Act</div>
    </header>
    """,
    unsafe_allow_html=True,
)

st.session_state.setdefault("transcript_input", SAMPLE_TRANSCRIPT)
st.session_state.setdefault("meeting_title", "Pilot launch review")

with st.sidebar:
    st.header("Meeting source")
    source = st.selectbox(
        "Source",
        [
            "Paste",
            "Upload",
            "Microsoft 365",
            "Teams",
            "Azure Blob",
            "Google Drive",
            "Zoom",
            "Outlook email",
            "Gmail",
        ],
        help="Choose where the meeting transcript will come from.",
    )
    if source != "Paste":
        source_panel(source)
    title = st.text_input(
        "Meeting title",
        key="meeting_title",
        help="Name used to identify this meeting in the extracted record and calendar draft.",
    )
    strategy_options = list(ExtractionStrategy)
    strategy = st.selectbox(
        "Extraction design",
        strategy_options,
        index=strategy_options.index(ExtractionStrategy.VERIFIED),
        help=(
            "Choose one AI pass, an extractor plus verifier, parallel specialists, or the "
            "non-AI rule-based demo."
        ),
        format_func=lambda item: item.value,
    )
    if strategy is not ExtractionStrategy.DEMO and not foundry_is_configured():
        st.warning("Foundry project configuration is missing.")

transcript_column, workspace_column = st.columns([0.9, 1.35], gap="large", vertical_alignment="top")

with transcript_column:
    transcript_text = st.text_area(
        "Transcript",
        key="transcript_input",
        height=360,
        placeholder="Paste the meeting transcript here",
        help="Meeting text used as the sole evidence source for extraction and grounded answers.",
    )
    imported = st.session_state.get("imported_document")
    if imported:
        with st.expander("Imported transcript details"):
            left, middle, right = st.columns(3)
            left.metric("Source", imported["source"])
            middle.metric("Lines", len(transcript_text.splitlines()))
            right.metric("Characters", len(transcript_text))
            st.caption(f"{imported['filename']} · SHA-256 {imported['content_hash'][:12]}…")

    if st.button("Extract meeting", type="primary", width="stretch"):
        st.session_state.extraction = None
        st.session_state.reviewed = None
        st.session_state.review_audit = None
        st.session_state.review_approved_at = None
        st.session_state.messages = []
        st.session_state.highlighted_lines = None
        try:
            with st.spinner(f"Running {strategy.value}…"):
                extraction = asyncio.run(extract_meeting(transcript_text, title, strategy))
            st.session_state.extraction = extraction
        except Exception as error:
            st.error(f"Extraction failed: {error}")

    extraction = st.session_state.get("extraction")
    if extraction:
        show_numbered_transcript(transcript_text)

with workspace_column:
    extraction = st.session_state.get("extraction")
    if extraction:
        for warning in extraction.warnings:
            st.warning(warning)
        with st.container(key="extraction_metrics"):
            metrics = st.columns(3)
            summaries = (
                ("Actions", len(extraction.actions)),
                ("Decisions", len(extraction.decisions)),
                ("Open questions", len(extraction.open_questions)),
            )
            for metric, (label, count) in zip(metrics, summaries):
                with metric:
                    st.markdown(f'<div class="summary-label">{label}</div>', unsafe_allow_html=True)
                    st.button(
                        str(count),
                        key=f"open_{label.lower().replace(' ', '_')}",
                        help=f"Open {label.lower()}",
                        on_click=request_review_tab,
                        args=(label,),
                        width="stretch",
                    )

        review_tab, chat_tab, calendar_tab = st.tabs(["Review", "Ask", "Calendar"])
        with review_tab:
            review_editor(extraction)
        reviewed = st.session_state.get("reviewed")
        with chat_tab:
            if reviewed:
                chat_panel(transcript_text, reviewed)
            else:
                st.info("Approve the reviewed record to ask grounded questions.")
        with calendar_tab:
            if reviewed:
                calendar_panel(reviewed)
            else:
                st.info("Approve the reviewed record to prepare a calendar event.")