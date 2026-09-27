# Meeting to Action

Extract grounded actions, decisions, and open questions from meeting transcripts; review the
result; ask cited questions; and prepare explicitly approved calendar events.

See [SYSTEM_DESIGN.md](SYSTEM_DESIGN.md) for the complete architecture, data flows, security
boundaries, deployment topology, reliability model, evaluation evidence, and production roadmap.

## Public documentation

- [Capstone documentation (PDF)](Meeting-to-Action-Capstone-Documentation.pdf)
- [System design (PDF)](Meeting-to-Action-System-Design.pdf)

Both PDF files are unencrypted and contain no Microsoft sensitivity or IRM label metadata.

## Live website

**Public URL:** https://ca-mta-nlmcnaci.greenground-3fac55c9.eastus2.azurecontainerapps.io/

The Streamlit application is deployed to Azure Container Apps in East US 2 with public HTTPS
ingress, a system-assigned managed identity, 0-1 replicas, and an authenticated Basic Azure
Container Registry with its admin user disabled. The hosted runtime uses
`ManagedIdentityCredential` and has `Foundry User` scoped to the
existing Microsoft Foundry project; `AcrPull` is scoped only to its registry. The existing
`gpt-5.4-mini` deployment remains unchanged.

Deployment verification on September 27, 2026 confirmed HTTP 200 from the application and
`/_stcore/health`, a healthy Container App revision, successful extractor-plus-verifier output
through managed identity, and clean post-request logs. The site is intentionally public and has no
user authentication, so anyone with the URL can submit transcript content and consume model quota.
Hosted delegated Microsoft, Google, and Zoom connector flows still require a server-safe OAuth
redesign; paste and upload plus Foundry extraction are verified live.

## Capstone architecture

### Problem statement

Meeting transcripts contain decisions, commitments, and unresolved questions, but manually
turning them into trustworthy follow-up records is slow and error-prone. This project solves one
narrow problem: convert a single meeting transcript into a human-approved, evidence-grounded
record whose actions can be queried and scheduled without losing traceability to the source.
The system does not attempt general organizational search or autonomous task execution.

### Data surface

The meeting transcript is the system's evidence knowledge base. Users can paste text, upload a
supported document, or actively query Microsoft 365, Teams, Azure Blob Storage, Google Drive,
Zoom, Outlook, or Gmail through the connector interface. Imported text is normalized into a
numbered transcript so every extracted record and answer can point back to an exact quote and
line range. Connector credentials and metadata are not sent to the model.

### Data processing

The ingestion pipeline validates file size and type, extracts text from TXT, VTT, SRT, DOCX, and
EML inputs, removes caption metadata, preserves speaker attribution, and normalizes content into
stable numbered lines. It computes a SHA-256 content hash, clears stale downstream state on a new
import, and retains exact source text for evidence validation. Teams VTT handling joins multiline
cues and merges adjacent speech from the same speaker before extraction.

### Retrieval design

Grounded Ask uses a hybrid RAG context:

1. BM25 ranks normalized transcript lines against the user's question.
2. The top eight matching lines are expanded by one neighboring line on each side to preserve
   conversational context.
3. Retrieved lines retain their original transcript numbers and are combined with the approved
   structured meeting record.
4. The answer model must cite exact evidence, and citations are validated against the full
   transcript rather than only the retrieved subset.

BM25 was chosen over an embedding index because the current corpus is one meeting at a time,
queries often contain exact names, deadlines, and domain terms, and line-level auditability is a
primary requirement. It adds no external vector service or embedding call. A vector or hybrid
semantic index becomes appropriate when retrieval expands across many meetings or paraphrase
recall becomes a measured weakness.

### Core flow

The application supports three Foundry-backed orchestration approaches plus a deterministic
non-AI demo:

1. **Single model:** one structured extraction call produces the complete meeting record.
2. **Extractor + verifier:** an extractor creates a draft and a second agent audits it against
   the transcript, removing unsupported content and correcting evidence.
3. **Specialists + consolidator:** action, decision, and question specialists run concurrently;
   a consolidator verifies and merges their candidates.
4. **Rule-based demo:** deterministic parsing for offline demonstrations; it is not a candidate
   production architecture.

After extraction, deterministic validation rejects quotes outside their declared transcript
lines and repairs supported line-range mismatches. Human review preserves the source evidence,
records field-level changes in a downloadable audit, and gates grounded Q&A and calendar actions.

## Run locally

1. Use Python 3.12 and install dependencies:
   `python -m pip install --pre -r requirements.txt`
2. Copy `.env.example` to `.env` and set the Foundry endpoint, model, and Azure CLI profile.
3. Sign in to the Azure CLI account that has **Azure AI User** on the Foundry project.
4. Start the app: `streamlit run app.py`

The deterministic demo strategy works without Foundry. The other three strategies use the
deployed model and reject evidence quotes or normalized deadline years not present in the
transcript.

## Transcript sources

Select a source in the sidebar. Paste and file upload work without provider configuration.
Uploads accept `.txt`, `.vtt`, `.srt`, `.docx`, and `.eml` files up to 10 MB. Caption cues and
timestamps are removed before extraction. Every import records a SHA-256 content hash, replaces
the current transcript, and clears stale extraction, review, and chat state.

Remote sources are read-only and activate only when their environment variables are present:

- **Microsoft 365:** Register a Microsoft Entra public client application, enable public client
   flows, and add delegated `Files.Read`, `Calendars.Read`, `OnlineMeetings.Read`,
   `OnlineMeetingTranscript.Read.All`, and `Mail.Read` Microsoft Graph permissions. Set
   `MICROSOFT_CLIENT_ID` and optionally `MICROSOFT_TENANT_ID`. Device sign-in covers OneDrive,
   SharePoint drives, Teams calendar meetings/transcripts, and Outlook attachments. Teams
   transcript access requires a work or school account, an unexpired meeting, and tenant-enabled
   Graph transcript access.
- **Azure Blob:** Set `AZURE_STORAGE_ACCOUNT_URL` and `AZURE_STORAGE_CONTAINER`; optionally set
   `AZURE_STORAGE_PREFIX`. The current Azure CLI or managed identity principal needs **Storage
   Blob Data Reader** on the container or account. The app does not create storage resources.
- **Google Drive and Gmail:** Create a Google OAuth desktop client, enable the Drive and Gmail
   APIs, and place its JSON at `GOOGLE_OAUTH_CREDENTIALS` (default `credentials.json`). The app
   requests only `drive.readonly` and `gmail.readonly`; its separate token defaults to
   `.google-workspace-token.json`.
- **Zoom:** Create a Server-to-Server OAuth app with cloud-recording read access. Set
   `ZOOM_ACCOUNT_ID`, `ZOOM_CLIENT_ID`, `ZOOM_CLIENT_SECRET`, and `ZOOM_USER_ID`. Only available
   transcript files from the last 30 days are listed.

Provider credentials, access tokens, source URLs, and connector metadata are never included in
model prompts. Imported transcript text is processed by the selected extraction strategy.

## Calendar providers

Create an OAuth 2.0 Desktop app in Google Cloud Console, enable the Google Calendar API, and
download its client JSON as `credentials.json`. The app previews the complete event body and
does not call Google until the approval checkbox is selected. OAuth tokens are stored locally
in the ignored `token.json` file.

Outlook / Microsoft 365 and Yahoo open a prefilled event draft in the selected provider; the
signed-in user reviews and saves it there. Apple Calendar, Thunderbird, Proton Calendar, and
other clients can use the `.ics` download. These draft/download paths do not collect provider
credentials and do not send invitations automatically.

## Evaluate architectures

Set `FOUNDRY_JUDGE_MODEL` to a deployed model different from `FOUNDRY_MODEL`, then run
`python -m meeting_to_action.evaluation`. The default run evaluates the six frozen test meetings;
use `--split development` while tuning or `--split all` for all 24 cases. Results are written to
`evaluation/results.json` with exact and semantic entity F1, evidence grounding, latency, and
model-call count.

The benchmark is reproducibly generated from AMI Meeting Corpus manual annotations (version
1.6.2, CC BY 4.0). It contains 24 annotation-linked excerpts: 18 development and six test cases,
with 75 actions, 169 decisions, and 137 open problems mapped to open questions. Rebuild it with
`python evaluation/build_ami_benchmark.py`; each record retains dataset version, license, source
meeting ID, and exact source dialogue evidence.

Each run combines deterministic and model-based evaluation:

- **Exact entity F1:** strict action, decision, and question matches against the labeled reference.
- **Semantic entity F1:** one-to-one, type-preserving matches using normalized MiniLM embeddings
   at a fixed 0.72 cosine threshold. Exact F1 remains the strict baseline.
- **Grounding rate:** proportion of evidence citations that pass deterministic quote/range checks.
- **Latency and model calls:** execution cost indicators for each generation architecture.
- **Independent LLM judge:** a separately configured Foundry deployment gives structured 1–5
  correctness, completeness, and grounding scores. The judge sees the transcript, reference,
  and candidate but not the architecture name.

### Human calibration

After an evaluation run, create a blinded two-reviewer packet:

```powershell
python -m meeting_to_action.calibration template
```

1. Open `evaluation/calibration_packet.json` and locate each opaque candidate ID.
2. Each reviewer independently fills their rows in `evaluation/human_ratings.csv` with integer
   1–5 correctness, completeness, and grounding scores. Do not discuss ratings first.
3. Calculate agreement with `python -m meeting_to_action.calibration score`.
4. Treat the judge as calibrated only when all 36 default packet ratings are complete, overall
   judge-to-human MAE is at most 0.75, and at least 80% of judge scores are within one point of
   the human mean. The report also records reviewer-to-reviewer MAE.

### Comparative results

The frozen test run evaluated all three architectures on six AMI meetings, producing 18
candidates. Every candidate was scored by the independent `gpt-4.1-judge` deployment.

| Approach | Exact F1 | Semantic F1 | Grounding | Judge C/C/G | Judge avg. | Latency | Generation calls |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Single model | 0.000 | 0.057 | 1.000 | 4.000 / 3.667 / 4.333 | 4.000 | 11.588 s | 1 |
| Extractor + verifier | 0.000 | 0.077 | 1.000 | 4.333 / 3.833 / 4.333 | 4.168 | 20.932 s | 2 |
| Specialists + consolidator | 0.000 | 0.045 | 1.000 | 4.333 / 4.333 / 4.167 | 4.278 | 32.995 s | 4 |

Exact matching is too brittle for these generated paraphrases, and semantic F1 remains low even
though deterministic grounding and judge scores are high. The metrics therefore support
different conclusions: the specialist flow has the highest judge average, the verifier has the
highest semantic F1, and the single model is fastest and cheapest. Latency is environment-dependent.

Two blinded reviewers completed all 36 human ratings. The judge passed the predefined calibration
criteria: overall judge-to-human MAE was 0.630 (maximum 0.750), 92.6% of dimension scores were
within one point of the human mean (minimum 80%), and reviewer-to-reviewer MAE was 0.111. Four of
54 judge-human dimension comparisons differed by more than one point. The largest was a grounding
false negative for `candidate-3ed031fbac4d`, where the judge scored 2 and both reviewers scored 5.
This residual error is retained as a limitation rather than resolved by changing human ratings.

**Final choice: Extractor + verifier.** It provides an explicit independent grounding check at
half the model-call count of the specialist architecture. The specialist flow is useful when
recall on dense meetings justifies extra cost, but the present evaluation shows no quality gain
for its two additional calls. The single model is cheapest, but it has no separate agent boundary
for catching unsupported records before deterministic validation. This makes extractor +
verifier the best current balance of reliability, explainability, and cost.

## Decision reasoning

- **Microsoft Agent Framework + Foundry:** supports typed structured responses and the single,
   sequential verifier, and concurrent specialist patterns within one SDK and model deployment.
- **Pydantic contracts:** reject malformed model responses before they reach review or calendar
   actions and make evaluation outputs machine-checkable.
- **Deterministic validation after LLM calls:** model confidence is not accepted as proof;
   evidence quotes, ranges, and deadline years are checked directly against source text.
- **BM25 retrieval:** fits exact-name and exact-deadline lookup in a single transcript while
   preserving transparent line-level provenance and avoiding premature vector infrastructure.
- **Extractor + verifier default:** adds an independent semantic audit while using two generation
   calls instead of the specialist flow's four, with equal or better measured quality here.
- **Streamlit interface:** provides a compact Azure-hosted UI for ingestion, human approval, change
   audit, grounded questions, and explicitly gated calendar actions without adding a separate web
   API.

## Failure analysis and pivots

### Unsupported or inaccurate evidence

- **Attempt:** accept structured model output directly.
- **Failure:** plausible records could contain unsupported quotes or incorrect line ranges.
- **Pivot:** require exact quote/line evidence in every record, add deterministic grounding
   validation and repair, and provide an extractor + verifier strategy. The UI surfaces repair
   warnings rather than silently hiding them.

### Teams transcript ingestion

- **Attempt:** process WebVTT uploads as ordinary text.
- **Failure:** cue identifiers, timestamps, markup, and split caption lines polluted extraction
   context and weakened evidence matching.
- **Pivot:** parse VTT cues, strip metadata and tags, preserve speakers, join multiline cues, and
   merge adjacent cues from the same speaker before numbering the transcript.

### Review approval after a hot reload

- **Attempt:** pass nested Pydantic evidence objects from Streamlit session state directly into
   rebuilt review records.
- **Failure:** after a module reload, retained instances had an older Python class identity and
   failed validation even though their displayed type was `Evidence`.
- **Pivot:** normalize evidence through plain Python dictionaries at the review boundary before
   constructing current model instances.

### Analytical meeting questions

- **Attempt:** require every answer to be explicitly stated verbatim in the transcript.
- **Failure:** useful questions such as requests for process improvements were rejected even when
   the transcript contained enough evidence for grounded analysis.
- **Pivot:** allow clearly labeled synthesis and recommendations when supported by exact meeting
   evidence, while continuing to reject unrelated questions and invented owners or deadlines.

### Full-context question answering

- **Attempt:** send the complete numbered transcript with every question.
- **Failure:** prompt size grows with transcript length and unrelated discussion competes with the
   evidence needed for the current question.
- **Pivot:** rank transcript lines with BM25, include neighboring conversational context, preserve
   original line numbers, and validate returned citations against the complete transcript.

### Scope and remaining risks

- AMI covers design and research meetings rather than every target business domain; future
   benchmark versions should add licensed real-world examples without tuning on the frozen test set.
- Semantic F1 depends on a fixed embedding model and threshold, so exact F1 and deterministic
   evidence validation remain separately reported.
- Independent-judge configuration prevents same-deployment self-scoring. Human calibration passed,
   but four dimension-level outliers show that judge scores must still be interpreted alongside
   deterministic metrics and reviewer evidence.
- Review history currently lives in Streamlit session state. Production audit retention requires
   authenticated persistent storage and reviewer identity.
- The live website is intentionally public; production use requires an approved authentication,
  authorization, abuse-prevention, and transcript-retention boundary.