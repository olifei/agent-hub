---
name: portal-ready
description: Prepare an ADK agent project for Agent Portal. Generates agent.yaml metadata, scans for GCP dependencies, checks or generates setup.sh, generates deploy.sh with optional Gemini Enterprise support, and runs agents-cli scaffold enhance. Use when a developer wants to make their agent deployable via Agent Portal.
disable-model-invocation: true
allowed-tools: Bash(grep *) Bash(find *) Bash(cat *) Bash(ls *) Bash(uvx *)
---

# Prepare Agent for Portal

You are helping a developer prepare their ADK agent project for inclusion in the Agent Portal. Follow these steps in order. At each step, present your findings and ask the developer to confirm before proceeding.

## Step 1: Analyze the project

Read the project's README.md, pyproject.toml, and agent code to understand:
- What the agent does
- What industry it serves
- What tools and capabilities it has
- What the agent directory name is (the directory containing agent.py with root_agent)

If you cannot find an agent.py with a `root_agent` definition, stop and tell the developer this is required.

## Step 2: Generate agent.yaml

Based on your analysis, generate an `agent.yaml` file with bilingual fields:

```yaml
name: <kebab-case name>
displayName:
  zh: <中文显示名>
  en: <English display name>
description:
  zh: <中文描述，2-3句>
  en: <English description, 2-3 sentences>
industry: <one of: content, customer-support, finance, technology, retail, healthcare, manufacturing, logistics, energy, telecom, education, government>
tags:
  - <tag1>
  - <tag2>
```

Present the generated agent.yaml to the developer and ask them to confirm or suggest changes. Only write the file after confirmation.

## Step 3: Scan for GCP service dependencies

Scan ALL Python files in the project for usage of GCP services. Look for:

- `google.cloud.storage` or `gcs` references → **Cloud Storage**
- `google.cloud.bigquery` or `bigquery` references → **BigQuery**
- `google.cloud.firestore` or `firestore` references → **Firestore**
- `google.cloud.secretmanager` or `secret` references → **Secret Manager**
- `google.cloud.spanner` → **Spanner**
- `google.cloud.pubsub` → **Pub/Sub**
- `google.cloud.discoveryengine` or `vertex_ai_search` → **Vertex AI Search**
- `google.cloud.alloydb` or `alloydb` or `psycopg2` → **AlloyDB**
- MCP tool connections (MCPToolset, StreamableHTTPConnectionParams) → **MCP Server**
- A2A references (to_a2a, a2a_sdk) → **A2A Service**
- Environment variables referencing external API keys → **External APIs**

Also check `.env.example`, `.env`, config files, and seed data directories (CSV, SQL, JSON files) for service and data references.

### Dependent Services (deploy-time)

Beyond GCP resources, check for services that must be **deployed before the agent**:

- `mcp_server/` directory with `deploy.sh` or `Dockerfile` → **MCP Server (Cloud Run)** — must be deployed first; agent needs its URL at runtime
- `a2a_server/` directory or `to_a2a` / `a2a_sdk` imports → **A2A Service** — must be deployed separately
- `os.environ["MCP_SERVER_URL"]` or similar required env vars that come from a deployed service → mark as **deploy-time env var**

If dependent services are detected, tell the developer:
> "Detected dependent service(s) that must deploy before the agent. deploy.sh will use multi-stage mode."

Present your findings organized as:
1. **GCP Resources** (APIs, buckets, IAM) — handled by setup.sh
2. **Dependent Services** (MCP Server, A2A) — need pre-deployment in deploy.sh
3. **External APIs** (YouTube API key, etc.) — user must provide

Ask the developer: "Are there any services or data dependencies I missed?"

## Step 4: Check or generate setup.sh

Check if `setup.sh` exists in the project root.

### If setup.sh exists — validate it

Read the script and check against this checklist:

| Check | What to look for |
|-------|-----------------|
| PROJECT_ID parameterized | Accepts project ID as argument, no hardcoded project IDs |
| No sensitive info | No API keys, passwords, or secrets in the script |
| Dependency consistency | All GCP services detected in Step 3 have corresponding setup commands |
| API enablement | Has `gcloud services enable` for each required API |
| IAM roles | Sets up necessary Service Account roles |
| Cleanup support | Supports `--cleanup` flag to remove created resources |
| Error handling | Has `set -e` or equivalent error checking |
| Tool availability | Only uses tools available in Cloud Shell (gcloud, bq, gsutil, python3, etc.) |
| Data file references | All referenced seed data files exist in the repo |
| Environment variable output | Writes created resource info to `.env` or prints for user |
| Cost warning | Mentions that paid resources will be created |
| Idempotent | Handles already-existing resources gracefully (skip or update, not fail) |

Ask the developer to fix any issues found.

### If setup.sh does not exist

If GCP services or seed data were detected in Step 3, generate a `setup.sh` following the standard template with argument parsing, cleanup support, and idempotent operations.

If no GCP services or data dependencies were detected, skip this step.

### Dependent service deployment scripts

If dependent services were detected in Step 3, verify their deployment scripts exist:

| Service Type | Required Files | Verify |
|---|---|---|
| MCP Server (Cloud Run) | `mcp_server/deploy.sh`, `mcp_server/Dockerfile` or `cloudbuild.yaml` | Script accepts `--project` and `--region`, outputs a service URL |
| A2A Service | `a2a_server/deploy.sh` | Script accepts `--project` and `--region` |

If the deployment script is missing, tell the developer they need to create it before proceeding. The skill does NOT generate dependent service deployment scripts — those are service-specific.

## Step 5: Ensure pyproject.toml has required configuration

Check if pyproject.toml contains both `[tool.agent-starter-pack]` and `[tool.agents-cli]`. Add whichever is missing:

```toml
[tool.agent-starter-pack]
base_template = "adk"

[tool.agent-starter-pack.settings]
agent_directory = "<detected_agent_directory>"
deployment_targets = ["agent_engine"]

[tool.agents-cli]
agent_directory = "<detected_agent_directory>"

[tool.agents-cli.create_params]
deployment_target = "agent_runtime"
```

Show the developer what will be added and confirm.

## Step 6: Run agents-cli scaffold enhance

Run the following command to add deployment infrastructure:

```bash
uvx google-agents-cli scaffold enhance --agent-directory <agent_dir> --deployment-target agent_runtime -s --yes
```

Show the output to the developer.

## Step 7: Generate deploy.sh

Create a `deploy.sh` in the project root. All agents must support both Agent Engine and Gemini Enterprise deployment via the `--ge APP_ID` option.

Choose the template based on Step 3 findings:
- **No dependent services** → Template A (Standard)
- **Has dependent services** (MCP Server, A2A, etc.) → Template B (Multi-stage)

### Template A: Standard deploy.sh

Use when the agent has no dependent services — just setup + Agent Engine + GE.

```bash
#!/bin/bash
set -e

# Parse arguments
GE_APP_ID=""
POSITIONAL=()
for arg in "$@"; do
  case $arg in
    --ge=*) GE_APP_ID="${arg#*=}" ;;
    --ge) GE_APP_ID="__NEXT__" ;;
    *)
      if [ "$GE_APP_ID" = "__NEXT__" ]; then
        GE_APP_ID="$arg"
      else
        POSITIONAL+=("$arg")
      fi
      ;;
  esac
done

PROJECT_ID="${POSITIONAL[0]:?Usage: bash deploy.sh <PROJECT_ID> [REGION] [--ge APP_ID]}"
REGION="${POSITIONAL[1]:-us-central1}"

echo "Deploying agent to project: $PROJECT_ID (region: $REGION)"
[ -n "$GE_APP_ID" ] && echo "  + Gemini Enterprise registration (APP_ID: $GE_APP_ID)"

# Create GCP resources if setup.sh exists
if [ -f setup.sh ]; then
    echo "Setting up GCP resources..."
    bash setup.sh "$PROJECT_ID" "$REGION"
fi

# Install dependencies
echo "Installing dependencies..."
uv sync
uv pip install google-agents-cli --python .venv/bin/python

# Deploy to Agent Engine
echo "Deploying to Agent Engine..."
gcloud config set project "$PROJECT_ID"
DEPLOY_OUTPUT=$(GOOGLE_CLOUD_PROJECT="$PROJECT_ID" GOOGLE_CLOUD_LOCATION="$REGION" \
  .venv/bin/agents-cli deploy --project "$PROJECT_ID" --region "$REGION" 2>&1 | tee /dev/stderr)

REASONING_ENGINE_ID=$(echo "$DEPLOY_OUTPUT" | grep -oP 'reasoningEngines/\K\d+' | tail -1)

echo ""
echo "Agent Engine deployment complete!"
[ -n "$REASONING_ENGINE_ID" ] && echo "  Reasoning Engine ID: $REASONING_ENGINE_ID"

# Register to Gemini Enterprise if --ge flag provided
if [ -n "$GE_APP_ID" ] && [ -n "$REASONING_ENGINE_ID" ]; then
    echo ""
    echo "Registering agent to Gemini Enterprise..."

    PROJECT_NUM=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
    ACCESS_TOKEN=$(gcloud auth print-access-token)

    AGENT_NAME="$(basename $(pwd))"
    if command -v python3 &>/dev/null && [ -f agent.yaml ]; then
        DISPLAY_NAME=$(python3 -c "
import yaml
d = yaml.safe_load(open('agent.yaml'))
dn = d.get('displayName', {})
print(dn.get('en', dn) if isinstance(dn, dict) else dn)
" 2>/dev/null || echo "$AGENT_NAME")
        AGENT_DESC=$(python3 -c "
import yaml
d = yaml.safe_load(open('agent.yaml'))
desc = d.get('description', {})
print(desc.get('en', desc) if isinstance(desc, dict) else desc)
" 2>/dev/null || echo "$DISPLAY_NAME")
    else
        DISPLAY_NAME="$AGENT_NAME"
        AGENT_DESC="$AGENT_NAME"
    fi

    REGISTER_RESPONSE=$(curl -s -X POST \
      "https://discoveryengine.googleapis.com/v1alpha/projects/${PROJECT_NUM}/locations/global/collections/default_collection/engines/${GE_APP_ID}/assistants/default_assistant/agents" \
      -H "Authorization: Bearer ${ACCESS_TOKEN}" \
      -H "Content-Type: application/json" \
      -H "X-Goog-User-Project: ${PROJECT_NUM}" \
      -d "{
        \"displayName\": \"${DISPLAY_NAME}\",
        \"description\": \"${AGENT_DESC}\",
        \"adk_agent_definition\": {
          \"tool_settings\": {
            \"tool_description\": \"${AGENT_DESC}\"
          },
          \"provisioned_reasoning_engine\": {
            \"reasoning_engine\": \"projects/${PROJECT_NUM}/locations/${REGION}/reasoningEngines/${REASONING_ENGINE_ID}\"
          }
        }
      }")

    if echo "$REGISTER_RESPONSE" | grep -q '"name"'; then
        echo "Gemini Enterprise registration successful!"
    else
        echo "Gemini Enterprise registration failed:"
        echo "$REGISTER_RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$REGISTER_RESPONSE"
    fi
elif [ -n "$GE_APP_ID" ] && [ -z "$REASONING_ENGINE_ID" ]; then
    echo "Skipping GE registration (Agent Engine deploy failed — no Reasoning Engine ID)"
fi

echo ""
echo "Deployment complete!"
```

### Template B: Multi-stage deploy.sh

Use when the agent has dependent services (e.g., MCP Server on Cloud Run). Adapt the template to the specific services detected. The example below shows MCP Server — adjust for A2A or other services.

```bash
#!/bin/bash
set -e

# =============================================================================
# <AGENT_DISPLAY_NAME> — Full Deployment
#
# Architecture:
#   1. setup.sh → GCP resources (APIs, buckets, IAM)
#   2. <DEPENDENT_SERVICE> → Cloud Run
#   3. Agent → Agent Engine (agents-cli deploy)
#   4. (optional) → Gemini Enterprise registration
#
# Usage:
#   bash deploy.sh <PROJECT_ID> [REGION] [--ge APP_ID]
# =============================================================================

GE_APP_ID=""
POSITIONAL=()
for arg in "$@"; do
  case $arg in
    --ge=*) GE_APP_ID="${arg#*=}" ;;
    --ge) GE_APP_ID="__NEXT__" ;;
    *)
      if [ "$GE_APP_ID" = "__NEXT__" ]; then
        GE_APP_ID="$arg"
      else
        POSITIONAL+=("$arg")
      fi
      ;;
  esac
done

PROJECT_ID="${POSITIONAL[0]:?Usage: bash deploy.sh <PROJECT_ID> [REGION] [--ge APP_ID]}"
REGION="${POSITIONAL[1]:-us-central1}"

# Calculate total steps (3 base + 1 if GE)
TOTAL_STEPS=3
[ -n "$GE_APP_ID" ] && TOTAL_STEPS=4

echo "═══════════════════════════════════════════════════════════"
echo "  <AGENT_DISPLAY_NAME> — Full Deployment"
echo "═══════════════════════════════════════════════════════════"
echo "  Project:  $PROJECT_ID"
echo "  Region:   $REGION"
[ -n "$GE_APP_ID" ] && echo "  GE App:   $GE_APP_ID"
echo "═══════════════════════════════════════════════════════════"

# ── Step 1: Setup GCP resources ──────────────────────────────────────────────

echo ""
echo "▸ Step 1/${TOTAL_STEPS}: Setting up GCP resources..."
if [ -f setup.sh ]; then
    bash setup.sh "$PROJECT_ID" "$REGION"
else
    echo "  (no setup.sh — skipped)"
fi

# ── Step 2: Deploy dependent service ────────────────────────────────────────
# ADAPT THIS SECTION to the specific dependent service detected.
# Example: MCP Server on Cloud Run

echo ""
echo "▸ Step 2/${TOTAL_STEPS}: Deploying <SERVICE_NAME> to Cloud Run..."

bash mcp_server/deploy.sh --project="$PROJECT_ID" --region="$REGION"

# Capture the service URL for the agent
MCP_SERVER_URL=$(gcloud run services describe <SERVICE_NAME> \
    --region="$REGION" --project="$PROJECT_ID" --format="value(status.url)")
echo "  Service URL: $MCP_SERVER_URL"

# ── Step 3: Deploy Agent to Agent Engine ─────────────────────────────────────

echo ""
echo "▸ Step 3/${TOTAL_STEPS}: Deploying Agent to Agent Engine..."

# Set env vars the agent needs from dependent services
export MCP_SERVER_URL="$MCP_SERVER_URL"
export GOOGLE_CLOUD_PROJECT="$PROJECT_ID"
export GOOGLE_CLOUD_LOCATION="$REGION"

uv sync
uv pip install google-agents-cli --python .venv/bin/python

gcloud config set project "$PROJECT_ID"
DEPLOY_OUTPUT=$(GOOGLE_CLOUD_PROJECT="$PROJECT_ID" GOOGLE_CLOUD_LOCATION="$REGION" \
    MCP_SERVER_URL="$MCP_SERVER_URL" \
    .venv/bin/agents-cli deploy --project "$PROJECT_ID" --region "$REGION" 2>&1 | tee /dev/stderr)

REASONING_ENGINE_ID=$(echo "$DEPLOY_OUTPUT" | grep -oP 'reasoningEngines/\K\d+' | tail -1)
echo "  Agent Engine deployment complete!"
[ -n "$REASONING_ENGINE_ID" ] && echo "  Reasoning Engine ID: $REASONING_ENGINE_ID"

# ── Step 4: Register to Gemini Enterprise (optional) ─────────────────────────

if [ -n "$GE_APP_ID" ] && [ -n "$REASONING_ENGINE_ID" ]; then
    echo ""
    echo "▸ Step 4/${TOTAL_STEPS}: Registering to Gemini Enterprise..."

    PROJECT_NUM=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
    ACCESS_TOKEN=$(gcloud auth print-access-token)

    AGENT_NAME="$(basename $(pwd))"
    if command -v python3 &>/dev/null && [ -f agent.yaml ]; then
        DISPLAY_NAME=$(python3 -c "
import yaml
d = yaml.safe_load(open('agent.yaml'))
dn = d.get('displayName', {})
print(dn.get('en', dn) if isinstance(dn, dict) else dn)
" 2>/dev/null || echo "$AGENT_NAME")
        AGENT_DESC=$(python3 -c "
import yaml
d = yaml.safe_load(open('agent.yaml'))
desc = d.get('description', {})
print(desc.get('en', desc) if isinstance(desc, dict) else desc)
" 2>/dev/null || echo "$DISPLAY_NAME")
    else
        DISPLAY_NAME="$AGENT_NAME"
        AGENT_DESC="$AGENT_NAME"
    fi

    REGISTER_RESPONSE=$(curl -s -X POST \
      "https://discoveryengine.googleapis.com/v1alpha/projects/${PROJECT_NUM}/locations/global/collections/default_collection/engines/${GE_APP_ID}/assistants/default_assistant/agents" \
      -H "Authorization: Bearer ${ACCESS_TOKEN}" \
      -H "Content-Type: application/json" \
      -H "X-Goog-User-Project: ${PROJECT_NUM}" \
      -d "{
        \"displayName\": \"${DISPLAY_NAME}\",
        \"description\": \"${AGENT_DESC}\",
        \"adk_agent_definition\": {
          \"tool_settings\": {
            \"tool_description\": \"${AGENT_DESC}\"
          },
          \"provisioned_reasoning_engine\": {
            \"reasoning_engine\": \"projects/${PROJECT_NUM}/locations/${REGION}/reasoningEngines/${REASONING_ENGINE_ID}\"
          }
        }
      }")

    if echo "$REGISTER_RESPONSE" | grep -q '"name"'; then
        echo "  Gemini Enterprise registration successful!"
    else
        echo "  Gemini Enterprise registration failed:"
        echo "$REGISTER_RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$REGISTER_RESPONSE"
    fi
elif [ -n "$GE_APP_ID" ] && [ -z "$REASONING_ENGINE_ID" ]; then
    echo ""
    echo "▸ Step 4/${TOTAL_STEPS}: Skipped (Agent Engine deploy failed — no Reasoning Engine ID)"
fi

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  ✅ Deployment Complete!"
echo "═══════════════════════════════════════════════════════════"
echo "  Service:   $MCP_SERVER_URL"
[ -n "$REASONING_ENGINE_ID" ] && echo "  Agent:     reasoningEngines/$REASONING_ENGINE_ID"
echo "═══════════════════════════════════════════════════════════"
```

**Important:** The `<PLACEHOLDERS>` in Template B must be replaced with actual values from Step 3:
- `<AGENT_DISPLAY_NAME>` — from agent.yaml or project analysis
- `<SERVICE_NAME>` — the Cloud Run service name from `mcp_server/deploy.sh`
- `<DEPENDENT_SERVICE>` — e.g., "MCP Server"
- Environment variable exports (e.g., `MCP_SERVER_URL`, `GCS_BUCKET_NAME`) — from the deploy-time env vars detected in Step 3

For agents with **multiple dependent services**, add additional Step sections (Step 2a, 2b, etc.) and adjust `TOTAL_STEPS` accordingly.

Present to developer and confirm before writing.

## Step 8: Verify

After all steps are complete, verify the project structure:

```bash
ls agent.yaml
ls deploy.sh
ls <agent_dir>/agent.py
grep "root_agent" <agent_dir>/agent.py
grep "agent-starter-pack" pyproject.toml
```

Present a summary:

```
✓ agent.yaml — metadata for Portal (bilingual)
✓ deploy.sh — one-click deployment script (with/without GE support)
✓ agent.py — has root_agent
✓ pyproject.toml — has ASP + agents-cli config
✓ setup.sh — resource setup script (if applicable)
✓ agents-cli enhance — deployment files added

Your agent is ready for Agent Portal!

Customer deployment flow:
  git clone https://github.com/olifei/agent-hub
  cd agent-hub/<agent-name>
  bash deploy.sh <PROJECT_ID>                    # Agent Engine only
  bash deploy.sh <PROJECT_ID> --ge <APP_ID>      # Agent Engine + Gemini Enterprise

Next: submit a PR to https://github.com/olifei/agent-hub
```
