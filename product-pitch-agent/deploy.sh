#!/bin/bash
set -e

# =============================================================================
# Product Pitch Agent — Full Deployment
#
# Architecture:
#   1. setup.sh → GCS bucket, APIs, IAM, Artifact Registry
#   2. MCP Server → Cloud Run (container build + deploy)
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
BUCKET_NAME="${PROJECT_ID}-pitch-agent-output"

TOTAL_STEPS=3
[ -n "$GE_APP_ID" ] && TOTAL_STEPS=4

echo "═══════════════════════════════════════════════════════════"
echo "  Product Pitch Agent — Full Deployment"
echo "═══════════════════════════════════════════════════════════"
echo "  Project:  $PROJECT_ID"
echo "  Region:   $REGION"
echo "  Bucket:   $BUCKET_NAME"
[ -n "$GE_APP_ID" ] && echo "  GE App:   $GE_APP_ID"
echo "═══════════════════════════════════════════════════════════"
echo ""

# ── Step 1: Setup GCP resources ──────────────────────────────────────────────

echo "▸ Step 1/${TOTAL_STEPS}: Setting up GCP resources..."
if [ -f setup.sh ]; then
    bash setup.sh "$PROJECT_ID" "$REGION"
fi

# ── Step 2: Deploy MCP Server to Cloud Run ───────────────────────────────────

echo ""
echo "▸ Step 2/${TOTAL_STEPS}: Deploying MCP Server to Cloud Run..."
echo "  (This builds a container and deploys — may take 3-5 minutes)"
echo ""

bash mcp_server/deploy.sh --project="$PROJECT_ID" --region="$REGION" --bucket="$BUCKET_NAME"

MCP_SERVER_URL=$(gcloud run services describe ads-video-mcp-server \
    --region="$REGION" --project="$PROJECT_ID" --format="value(status.url)")

echo ""
echo "  MCP Server URL: $MCP_SERVER_URL"

# ── Step 3: Deploy Agent to Agent Engine ─────────────────────────────────────

echo ""
echo "▸ Step 3/${TOTAL_STEPS}: Deploying Agent to Agent Engine..."
echo ""

export MCP_SERVER_URL="$MCP_SERVER_URL"
export GCS_BUCKET_NAME="$BUCKET_NAME"
export GOOGLE_CLOUD_PROJECT="$PROJECT_ID"
export GOOGLE_CLOUD_LOCATION="$REGION"

uv sync
uv pip install google-agents-cli --python .venv/bin/python

gcloud config set project "$PROJECT_ID"
DEPLOY_OUTPUT=$(GOOGLE_CLOUD_PROJECT="$PROJECT_ID" GOOGLE_CLOUD_LOCATION="$REGION" \
    MCP_SERVER_URL="$MCP_SERVER_URL" GCS_BUCKET_NAME="$BUCKET_NAME" \
    .venv/bin/agents-cli deploy --project "$PROJECT_ID" --region "$REGION" 2>&1 | tee /dev/stderr)

REASONING_ENGINE_ID=$(echo "$DEPLOY_OUTPUT" | grep -oP 'reasoningEngines/\K\d+' | tail -1)

echo ""
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
echo ""
echo "  MCP Server:  $MCP_SERVER_URL"
[ -n "$REASONING_ENGINE_ID" ] && echo "  Agent:       reasoningEngines/$REASONING_ENGINE_ID"
echo "  GCS Bucket:  gs://$BUCKET_NAME"
echo ""
echo "  Try in Playground or Gemini Enterprise!"
echo "═══════════════════════════════════════════════════════════"
