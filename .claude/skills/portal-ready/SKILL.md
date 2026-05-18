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

Present your findings and ask the developer: "Are there any services or data dependencies I missed?"

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

Create a `deploy.sh` in the project root. All agents must support both Agent Engine and Gemini Enterprise deployment via the `--ge APP_ID` option:

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

# Extract reasoning engine ID
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

    # Get agent info from agent.yaml
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
        echo "$REGISTER_RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$REGISTER_RESPONSE"
    else
        echo "Gemini Enterprise registration failed:"
        echo "$REGISTER_RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$REGISTER_RESPONSE"
    fi
fi

echo ""
echo "Deployment complete!"
```


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
