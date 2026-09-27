# Azure Deployment Plan

> **Status:** Deployed
>
> Foundry baseline: Deployed. Website hosting extension: Deployed and verified.

Generated: 2026-09-22
Website hosting extension updated: 2026-09-27

---

## 1. Project Overview

**Goal:** Host the completed Meeting-to-Action Streamlit application on Azure with public HTTPS ingress, managed-identity access to the existing Foundry project, private image storage, and centralized logs.

**Path:** Add Components to the deployed Foundry baseline

---

## 2. Requirements

| Attribute | Value |
|-----------|-------|
| Classification | POC |
| Scale | Small |
| Budget | Cost-Optimized |
| Subscription | Visual Studio Enterprise Subscription (`b7e642af-d77d-4136-b001-feb73d2467a0`), confirmed by user |
| Location | East US 2, confirmed by user |
| Website access | Public internet, explicitly selected by user |
| Hosting | Azure Container Apps Consumption, explicitly selected by user |
| Container allocation | 1 vCPU, 2 GiB memory |
| Replica range | 0 minimum, 1 maximum |

---

## 3. Components Detected

| Component | Type | Technology | Path |
|-----------|------|------------|------|
| Infrastructure | Infrastructure as Code | Bicep + Azure Developer CLI metadata | `infra/`, `azure.yaml` |
| Application | Interactive web prototype | Python + Streamlit, pending implementation | Project root |
| Agent layer | Extraction, verification, grounded chat, tools | Microsoft Agent Framework for Python + Foundry `AIProjectClient`, pending implementation | Project root |

---

## 4. Recipe Selection

**Selected:** Azure CLI with Bicep

**Rationale:** The generated azd Bicep remains the source of truth, but direct Azure CLI deployment uses the isolated authenticated profile and avoids an azd MFA token limitation. A standard ARM parameter file preserves nested model JSON types.

---

## 5. Architecture

**Stack:** Local Streamlit prototype backed by Microsoft Foundry

### Service Mapping

| Component | Azure Service | SKU |
|-----------|---------------|-----|
| Model and agent project | Microsoft Foundry / Azure AI Services | S0 account |
| Primary model | `gpt-5.4-mini` version `2026-03-17` | GlobalStandard, capacity 10 |
| Telemetry | Application Insights | Workspace-based |
| Logs | Log Analytics | PerGB2018 |

### Supporting Services

| Service | Purpose |
|---------|---------|
| Microsoft Foundry project | Model access and agent project boundary |
| Application Insights | Application and agent telemetry |
| Log Analytics | Centralized telemetry storage |
| Managed identities | Foundry account and project identities |
| Azure RBAC | Project-scoped Azure AI User access for the developer |

Local authentication uses `AzureCliCredential`; local secrets will not be committed. Model local authentication is disabled. Calendar writes require a preview and explicit human approval.

### Website Hosting Extension

| Component | Azure Service | Configuration |
|-----------|---------------|---------------|
| Website | Azure Container Apps | Consumption, public HTTPS, port 8501, 0-1 replicas |
| Container image | Azure Container Registry | Basic, private, anonymous pull disabled |
| Runtime authentication | System-assigned managed identity | No stored Azure credential |
| Image authorization | Azure RBAC | `AcrPull` at registry scope |
| Model authorization | Azure RBAC | `Azure AI User` at the existing Foundry project scope |
| Logs | Existing Log Analytics workspace | Container console and system logs |

The application will use `AzureCliCredential` locally and `ManagedIdentityCredential` in Azure.
The image will exclude `.env`, `.azure`, local OAuth tokens, evaluation data, tests, and generated
documents. Google, Zoom, and delegated Microsoft connectors remain unavailable in the hosted POC
until server-safe OAuth callback and secret-storage designs are added. Paste, file upload, Foundry
extraction, grounded Ask, calendar links, and ICS export remain available.

Public access means anyone with the URL can upload transcript content and consume model quota. The
hosted POC must not be used for confidential or personal data. Microsoft Entra authentication is the
required follow-up before sensitive use.

#### Runtime Flow

1. Public HTTPS traffic reaches Container Apps ingress on port 8501.
2. Streamlit stores active workflow data in per-session memory.
3. The container's managed identity calls the existing Foundry project.
4. The identity pulls the private image from ACR through `AcrPull` RBAC.
5. Container logs flow to the existing Log Analytics workspace.

#### Cost Estimate

Retail rates queried on 2026-09-27 for East US 2:

| Meter | Retail rate | Approximation |
|-------|-------------|---------------|
| ACR Basic registry unit | USD 0.1666/day | About USD 5.07/month |
| ACR storage | USD 0.10/GB-month | Image-size dependent |
| Container Apps active vCPU | USD 0.000024/vCPU-second | About USD 2.59/month at 1 active hour/day |
| Container Apps active memory | USD 0.000003/GiB-second | About USD 0.65/month at 2 GiB and 1 active hour/day |
| Container Apps requests | USD 0.40/million | Traffic dependent |
| Environment management meter | USD 0.10/hour | Catalog upper bound of about USD 73/month if applicable continuously |

Expected hosting cost is usage-dependent: approximately USD 5/month for ACR plus Container Apps
compute, requests, logs, and any applicable environment charge. Existing Foundry model usage and Log
Analytics ingestion are separate. Azure billing is authoritative.

#### Research Summary

| Area | Selected guidance |
|------|-------------------|
| Container Apps | `Microsoft.App/containerApps@2025-01-01`; external HTTPS-only ingress, system identity, single revision, 0-1 replicas, and explicit HTTP probes |
| Managed environment | `Microsoft.App/managedEnvironments@2025-01-01`; reuse the existing Log Analytics workspace |
| Registry | `Microsoft.ContainerRegistry/registries@2025-04-01`; Basic SKU, admin user disabled, anonymous pull disabled |
| Image pull | Provision the app with a public placeholder, then assign `AcrPull` in a separate module; azd attaches the system identity to ACR before publishing the application image |
| azd discovery | Add a `web` service and the `azd-service-name: web` resource tag; emit registry and website outputs from Bicep |
| Python identity | Use `ManagedIdentityCredential` only when the hosted runtime marker is set; retain `AzureCliCredential` for local development |
| Container security | Python 3.12 slim image, non-root user, no embedded credentials, and a minimal production dependency set |

Sources: Azure Prepare Container Apps, health probe, Docker, azd schema, and Bicep IaC references;
Azure Bicep resource schemas queried on 2026-09-27; Azure AI application best practices queried on
2026-09-27. No suitable AVM+azd pattern module was available through the installed tooling, so the
website uses focused resource modules consistent with the repository's existing Bicep structure.

---

## 6. Provisioning Limit Checklist

| Resource Type | Number to Deploy | Total After Deployment | Limit/Quota | Notes |
|---------------|------------------|------------------------|-------------|-------|
| `Microsoft.Resources/resourceGroups` | 1 | 1 target group | Subscription limit not approached | Target group does not currently exist; checked 2026-09-22 |
| `Microsoft.CognitiveServices/accounts` | 1 | 1 in target group | ARM validation accepted | `AIServices` S0 account in East US 2 |
| `Microsoft.CognitiveServices/accounts/deployments` | 1 | 10 capacity units requested | At least 10 GlobalStandard units available | Foundry catalog and quota preflight confirmed `gpt-5.4-mini` availability before model selection |
| `Microsoft.CognitiveServices/accounts/projects` | 1 | 1 in target group | ARM validation accepted | Project name `ai-project-meetingtoaction` |
| `Microsoft.OperationalInsights/workspaces` | 1 | 1 in target group | ARM validation accepted | Monitoring enabled |
| `Microsoft.Insights/components` | 1 | 1 in target group | ARM validation accepted | Workspace-based Application Insights |
| `Microsoft.CognitiveServices/accounts/projects/connections` | 1 | 1 in target project | ARM validation accepted | Application Insights connection |
| `Microsoft.Authorization/roleAssignments` | 1 | 1 project-scoped assignment | Subscription Owner role verified | Azure AI User assigned to the signed-in developer |
| `Microsoft.App/managedEnvironments` | 1 | 1 in East US 2 | Subscription-specific | Quota API did not return a numeric limit; ARM what-if and validation are mandatory gates |
| `Microsoft.App/containerApps` | 1 | 1 in East US 2 | Consumption environment quota | 0-1 replicas and 1 vCPU requested |
| `Microsoft.ContainerRegistry/registries` | 1 | 1 in East US 2 | No blocking limit identified | Basic SKU, anonymous pull disabled |
| `Microsoft.Authorization/roleAssignments` | 2 | 3 app-related assignments | Subscription Owner role previously verified | Add `AcrPull` and project-scoped `Azure AI User` for the app identity |

**Status:** Existing Foundry resources remain within checked limits. The Azure quota tool could not
read Container Apps quota for this subscription; official guidance states defaults vary by
subscription and region. Deployment is blocked until Bicep compilation and ARM what-if/validation
confirm that one East US 2 environment and one 1-vCPU replica can be provisioned. The Azure CLI
session expired on 2026-09-27, so fresh interactive MFA is required before validation.

---

## 7. Execution Checklist

### Phase 1: Planning
- [x] Analyze workspace
- [x] Gather requirements
- [x] Confirm subscription and location with user
- [x] Prepare resource inventory
- [x] Check model availability and quota
- [x] Scan infrastructure
- [x] Select deployment recipe
- [x] Plan architecture
- [x] User approved subscription, region, project, model, SKU, capacity, and monitoring configuration

### Phase 2: Execution
- [x] Research Foundry and deployment best practices
- [x] Generate infrastructure files
- [x] Generate ARM parameter file
- [x] Configure managed identity and project-scoped RBAC
- [x] Update plan status to `Ready for Validation`

### Phase 3: Validation
- [x] Invoke azure-validate workflow
- [x] Validate Azure context and target resource-group state
- [x] Compile the Bicep template
- [x] Validate the subscription-scope ARM deployment
- [x] Review static RBAC assignments
- [x] Record validation proof
- [x] Update plan status to `Validated`

### Phase 4: Deployment
- [x] Invoke azure-deploy workflow
- [x] Deploy the subscription-scope Bicep template
- [x] Verify resource provisioning and RBAC
- [x] Verify the Foundry project and model deployment
- [x] Record deployment outputs
- [x] Update plan status to `Deployed`

### Website Hosting Extension: Planning
- [x] Analyze the completed Streamlit application
- [x] Confirm subscription, resource group, and East US 2
- [x] Confirm public access and Container Apps Consumption
- [x] Review subscription policies
- [x] Query retail prices and document cost uncertainty
- [x] Inventory existing resources and hosting additions
- [x] User approves the hosting plan, estimated charges, and public-access risk

### Website Hosting Extension: Preparation
- [x] Add deterministic local-versus-hosted Azure credential selection
- [x] Add runtime-only Python requirements
- [x] Add Dockerfile and `.dockerignore`
- [x] Add the `web` Container Apps service to `azure.yaml`
- [x] Add ACR, Container Apps environment, Container App, and scoped RBAC Bicep
- [x] Configure port 8501, health probes, public HTTPS ingress, and 0-1 replicas
- [x] Check local image-build availability; Docker is not installed, so use ACR build during deployment
- [x] Run the full Python test suite: 43 passed on 2026-09-27
- [x] Compile Bicep with no diagnostics in the new hosting modules
- [x] Verify the local Streamlit health endpoint returns HTTP 200
- [x] Set plan status to `Ready for Validation`

### Website Hosting Extension: Validation
- [x] Run the azure-validate workflow
- [x] All validation checks pass
	- [x] 1. AZD Installation: 1.34.2 installed and invoked directly
	- [x] 2. Schema Validation
	- [x] 3. Environment Setup
	- [x] 4. Authentication Check: delegated to Azure CLI after browser MFA
	- [x] 5. Subscription/Location Check
	- [x] 6. Aspire Pre-Provisioning Checks (not applicable)
	- [x] 7. Provision Preview
	- [x] 8. Build Verification: 43 tests passed and Python compiled
	- [x] 9. Docker Build Context Validation
	- [x] 10. Package Validation: remote build configuration packaged successfully
	- [x] 11. Azure Policy Validation
	- [x] 12. Aspire Post-Provisioning Checks (not applicable)
- [x] Compile and lint Bicep
- [x] Run ARM what-if and deployment validation after fresh MFA
- [x] Verify no secrets or local token files enter the image
- [x] Record validation proof
- [x] Set plan status to `Validated`

### Website Hosting Extension: Deployment
- [x] Run the azure-deploy workflow
- [x] Provision ACR, managed environment, container app, and RBAC
- [x] Build and push the application image
- [x] Verify `AcrPull` propagation before activating the image
- [x] Attach the Container App system identity to the private ACR
- [x] Verify public HTTPS, Streamlit health, logs, and one Foundry extraction
- [x] Report the fully qualified URL and live Azure role assignments
- [x] Set plan status to `Deployed`

---

## 8. Validation Proof

| Check | Command Run | Result | Timestamp |
|-------|-------------|--------|-----------|
| Azure context | `az account show --subscription b7e642af-d77d-4136-b001-feb73d2467a0` | Pass: correct subscription and tenant | 2026-09-22T15:30:48Z |
| Target resource group | `az group exists --name rg-meetingtoaction` | Pass: `false`, clean deployment target | 2026-09-22T15:30:48Z |
| Bicep build | `az bicep build --file .\infra\main.bicep --stdout` | Pass | 2026-09-22T15:30:48Z |
| ARM deployment validation | `az deployment sub validate --template-file .\infra\main.bicep --parameters @.\.azure\meetingtoaction\arm.parameters.json` | Pass: `Succeeded`, no ARM error | 2026-09-22T15:30:48Z |
| Static RBAC review | Review active role assignments in `ai-project.bicep` and `applicationinsights.bicep` | Pass: required data access is resource-scoped | 2026-09-22T15:30:48Z |
| Website azd schema | Azure MCP `validate_azure_yaml` | Pass: valid stable schema | 2026-09-27T12:36:20Z |
| Website build | `python -m pytest -q` and `python -m compileall -q app.py meeting_to_action` | Pass: 43 tests and compilation | 2026-09-27T12:36:20Z |
| Website package | `azd package --no-prompt` | Pass: `web` packaged for remote build | 2026-09-27T12:36:20Z |
| Website provision preview | `azd provision --preview --no-prompt` | Pass: create Container App, environment, and registry; existing Foundry and monitoring resources skipped | 2026-09-27T12:36:20Z |
| Website ARM validation | `validate-deployment.ps1 -Scope sub -Location eastus2` | Pass: build and ARM validation; Create 4, Modify 0, Delete 0 | 2026-09-27T12:36:20Z |
| Website policy review | Azure MCP `policy_assignment_list` | Pass: East US 2 allowed; MFA write/delete policies satisfied; Security Center policies are audit-only | 2026-09-27T12:36:20Z |
| Website container hygiene | Review `Dockerfile` and `.dockerignore` | Pass: local credentials, Azure state, tokens, tests, and generated data excluded | 2026-09-27T12:36:20Z |

### Role Assignment Verification

- Status: Verified
- Developer identity: Azure AI User (`53ca6127-db72-4b80-b1b0-d745d6d5456d`) scoped to the Foundry project.
- Foundry project managed identity: Log Analytics Reader (`73c42c96-874c-492b-b04d-ab87d138a893`) scoped to Application Insights.
- Website Container App system identity: AcrPull (`7f951dda-4ed3-4680-a7ca-43fe172d538d`) scoped to the website registry.
- Website Container App system identity: Azure AI User (`53ca6127-db72-4b80-b1b0-d745d6d5456d`) scoped to the existing Foundry project.
- Hosted runtime selects `ManagedIdentityCredential`; local development continues to select `AzureCliCredential`.
- No generated assignment is scoped to the subscription or resource group.

### Deployment Verification

- ARM deployment `meetingtoaction-20260922`: `Succeeded` at 2026-09-22T15:37:17Z.
- Live verification: passed at 2026-09-22T15:42:04Z.
- Resources: Foundry/AIServices account, Foundry project, Application Insights, and Log Analytics.
- Model: `gpt-5.4-mini`, version `2026-03-17`, GlobalStandard capacity 10, provisioning state `Succeeded`.
- Security: Cognitive Services local authentication disabled.
- Live RBAC: Azure AI User at project scope and Log Analytics Reader at Application Insights scope.
- Foundry project endpoint: `https://ai-account-nlmcnaciofa6y.services.ai.azure.com/api/projects/ai-project-meetingtoaction`
- Azure OpenAI endpoint: `https://ai-account-nlmcnaciofa6y.openai.azure.com/`

### Website Deployment Verification

- Deployment: `meetingtoaction-1790512947`; infrastructure provisioning succeeded on 2026-09-27.
- Public endpoint: `https://ca-mta-nlmcnaci.greenground-3fac55c9.eastus2.azurecontainerapps.io/`.
- Streamlit health: `/_stcore/health` returned HTTP 200 with `ok`; the root page returned HTTP 200.
- Active application revision: `ca-mta-nlmcnaci--azd-1790513931`, healthy and provisioned.
- Image: `crmtanlmcnaciof.azurecr.io/ai-foundry-starter-basic/web-meetingtoaction:azd-deploy-1790513849`.
- Runtime: public HTTPS only, port 8501, system-assigned identity, single revision mode, 0-1 replicas.
- Registry: `crmtanlmcnaciof`, Basic SKU, admin user disabled; system identity registry binding configured.
- Live RBAC: `AcrPull` at registry scope and `Foundry User` at existing Foundry project scope for principal `c4ddb24e-cd01-40c0-b71f-94d6dd78d584`.
- Managed-identity extraction: production UI returned 1 action, 1 decision, 1 open question, and grounded notes using `Extractor + verifier`.
- Runtime cleanup: Agent Framework clients now close after each call; final revision logs contain no unclosed-session, connector, or authentication errors.
- Foundry preservation: `gpt-5.4-mini` remains version `2026-03-17`, GlobalStandard capacity 10, provisioning state `Succeeded`.
- Final tests: 44 passed; Python compilation and editor diagnostics passed.
- Inventory: six pre-existing resources plus the expected ACR, Container Apps environment, and Container App; no existing baseline resource was modified or deleted by the validated what-if.

**Validated by:** azure-validate workflow
**Website validation timestamp:** 2026-09-27T12:36:20Z
**Website deployment timestamp:** 2026-09-27T13:03:10Z

---

## 9. Files

| File | Purpose | Status |
|------|---------|--------|
| `.azure/deployment-plan.md` | Deployment source of truth | Complete |
| `azure.yaml` | Azure Developer CLI project metadata | Complete |
| `infra/main.bicep` | Subscription-scope infrastructure | Complete |
| `infra/main.parameters.json` | azd parameter mapping | Complete |
| `.azure/meetingtoaction/arm.parameters.json` | Environment-local direct ARM parameters | Complete, Git-ignored |
| `Dockerfile` | Non-root Streamlit production image | Complete |
| `.dockerignore` | Excludes local credentials, Azure state, tests, and generated data | Complete |
| `requirements.runtime.txt` | Production-only Python dependencies | Complete |
| `infra/core/host/web-registry.bicep` | Private Basic ACR | Complete |
| `infra/core/host/web-container-app.bicep` | Managed environment and public Streamlit Container App | Complete |
| `infra/core/host/web-role-assignments.bicep` | Scoped `AcrPull` and `Azure AI User` assignments | Complete |

---

## 10. Next Steps

> Current: The public website is deployed and verified at
> `https://ca-mta-nlmcnaci.greenground-3fac55c9.eastus2.azurecontainerapps.io/`.

1. Monitor Container Apps and Foundry usage while public access remains enabled.
2. Add Microsoft Entra authentication, authorization, and abuse controls before enterprise use.
3. Redesign delegated connector OAuth and token storage before enabling those connectors in the hosted runtime.