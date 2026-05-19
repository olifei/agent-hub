#!/bin/bash
# Deploy MCP Server to Cloud Run with Cloud Run Jobs
#
# Architecture:
#   Client → Cloud Run (IAM or IAP auth) → Cloud Run Job (Pipeline)
#                                         → GCS (explicit uploads via GCS API)
#
# Usage:
#   # IAM-only auth (default — simpler setup)
#   bash mcp_server/deploy.sh --project=my-project --region=us-central1
#
#   # With IAP auth (requires OAuth consent screen + backend service)
#   bash mcp_server/deploy.sh --project=my-project --iap --iap-members="user:a@x.com"
#
#   # Custom bucket and service name
#   bash mcp_server/deploy.sh --project=my-project --bucket=my-bucket --service=my-mcp

set -euo pipefail

# ── Configuration ────────────────────────────────────────────────────────────

PROJECT_ID="${GCP_PROJECT_ID:-}"
REGION="${GCP_REGION:-us-central1}"
SERVICE_NAME="${MCP_SERVICE_NAME:-ads-video-mcp-server}"
JOB_NAME="${PIPELINE_JOB_NAME:-ads-video-pipeline-job}"
AR_REPO="${AR_REPO:-mcp-server}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
GCS_BUCKET="${GCS_BUCKET_NAME:-}"
GCS_PREFIX="${GCS_PREFIX:-mcp-pipeline}"
PREVIEW_LOCATION="${VERTEX_AI_PREVIEW_LOCATION:-global}"
IAP_MEMBERS="${IAP_MEMBERS:-}"  # Comma-separated: user:a@x.com,user:b@x.com
ENABLE_IAP=false

for arg in "$@"; do
    case $arg in
        --project=*) PROJECT_ID="${arg#*=}" ;;
        --region=*) REGION="${arg#*=}" ;;
        --service=*) SERVICE_NAME="${arg#*=}" ;;
        --bucket=*) GCS_BUCKET="${arg#*=}" ;;
        --tag=*) IMAGE_TAG="${arg#*=}" ;;
        --iap) ENABLE_IAP=true ;;
        --iap-members=*) IAP_MEMBERS="${arg#*=}"; ENABLE_IAP=true ;;
        *) echo "Unknown flag: $arg"; exit 1 ;;
    esac
done

if [ -z "$PROJECT_ID" ]; then
    PROJECT_ID=$(gcloud config get-value project 2>/dev/null)
    [ -z "$PROJECT_ID" ] && { echo "❌ Set GCP_PROJECT_ID or --project=..."; exit 1; }
fi

PROJECT_NUMBER=$(gcloud projects describe "${PROJECT_ID}" --format="value(projectNumber)")
IMAGE_URI="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/${SERVICE_NAME}:${IMAGE_TAG}"

AUTH_MODE="IAM-only"
if [ "$ENABLE_IAP" = true ]; then
    AUTH_MODE="IAP (Google OAuth)"
fi

echo "═══════════════════════════════════════════════════════════"
echo "  Deploy: MCP Server + Cloud Run Job"
echo "═══════════════════════════════════════════════════════════"
echo "  Project:  ${PROJECT_ID} (${PROJECT_NUMBER})"
echo "  Region:   ${REGION}"
echo "  Service:  ${SERVICE_NAME}"
echo "  Job:      ${JOB_NAME}"
echo "  Auth:     ${AUTH_MODE}"
echo "═══════════════════════════════════════════════════════════"

# ── Step 1: Enable APIs ──────────────────────────────────────────────────────

echo -e "\n🔧 Step 1: Enabling APIs..."
APIS="run.googleapis.com compute.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com"
if [ "$ENABLE_IAP" = true ]; then
    APIS="${APIS} iap.googleapis.com"
fi
gcloud services enable ${APIS} --project="${PROJECT_ID}" --quiet

# ── Step 2: Artifact Registry ────────────────────────────────────────────────

echo -e "\n📦 Step 2: Artifact Registry..."
gcloud artifacts repositories describe "${AR_REPO}" \
    --project="${PROJECT_ID}" --location="${REGION}" \
    --format="value(name)" 2>/dev/null || \
gcloud artifacts repositories create "${AR_REPO}" \
    --project="${PROJECT_ID}" --location="${REGION}" \
    --repository-format=docker --description="MCP Server images"

# ── Step 3: Build & push image ───────────────────────────────────────────────

echo -e "\n🐳 Step 3: Building container image (Cloud Build)..."

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
gcloud builds submit "${PROJECT_ROOT}" \
    --config="${PROJECT_ROOT}/cloudbuild.yaml" \
    --substitutions="_IMAGE_URI=${IMAGE_URI}" \
    --project="${PROJECT_ID}" \
    --region="${REGION}" \
    --quiet

# ── Step 4: Deploy Cloud Run Job (pipeline runner) ───────────────────────────

echo -e "\n⚙️  Step 4: Cloud Run Job (pipeline runner)..."
JOB_ENV="VERTEX_AI_PROJECT_ID=${PROJECT_ID},VERTEX_AI_LOCATION=${REGION},VERTEX_AI_PREVIEW_LOCATION=${PREVIEW_LOCATION},GCS_PREFIX=${GCS_PREFIX}"
[ -n "$GCS_BUCKET" ] && JOB_ENV="${JOB_ENV},GCS_BUCKET_NAME=${GCS_BUCKET}"
JOB_FLAGS=(
    --image="${IMAGE_URI}"
    --region="${REGION}" --project="${PROJECT_ID}"
    --memory=4Gi --cpu=2 --task-timeout=3600 --max-retries=1
    --set-env-vars="${JOB_ENV}"
    --command="python,-m,mcp_server.pipeline_runner"
)
gcloud run jobs describe "${JOB_NAME}" --region="${REGION}" --project="${PROJECT_ID}" &>/dev/null \
    && gcloud run jobs update "${JOB_NAME}" "${JOB_FLAGS[@]}" \
    || gcloud run jobs create "${JOB_NAME}" "${JOB_FLAGS[@]}"

# ── Step 5: Deploy Cloud Run Service ─────────────────────────────────────────

echo -e "\n🚀 Step 5: Cloud Run Service..."
SVC_ENV="VERTEX_AI_PROJECT_ID=${PROJECT_ID},VERTEX_AI_LOCATION=${REGION},VERTEX_AI_PREVIEW_LOCATION=${PREVIEW_LOCATION},GCS_PREFIX=${GCS_PREFIX},EXECUTION_MODE=cloud_run_jobs,PIPELINE_JOB_NAME=${JOB_NAME}"
[ -n "$GCS_BUCKET" ] && SVC_ENV="${SVC_ENV},GCS_BUCKET_NAME=${GCS_BUCKET}"
SERVICE_FLAGS=(
    --image="${IMAGE_URI}"
    --region="${REGION}" --project="${PROJECT_ID}"
    --port=8080 --memory=1Gi --cpu=1 --timeout=60
    --concurrency=20 --min-instances=0 --max-instances=3
    --no-allow-unauthenticated
    --set-env-vars="${SVC_ENV}"
)

if [ "$ENABLE_IAP" = true ]; then
    SERVICE_FLAGS+=(--iap)
else
    SERVICE_FLAGS+=(--no-iap)
fi

gcloud run deploy "${SERVICE_NAME}" "${SERVICE_FLAGS[@]}"

SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" \
    --region="${REGION}" --project="${PROJECT_ID}" --format="value(status.url)")

# ── Step 6: Grant access ─────────────────────────────────────────────────────

echo -e "\n🔒 Step 6: Granting access..."

SA_EMAIL="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

if [ "$ENABLE_IAP" = true ] && [ -n "$IAP_MEMBERS" ]; then
    # IAP mode: grant IAP access
    IFS=',' read -ra MEMBERS <<< "$IAP_MEMBERS"
    for MEMBER in "${MEMBERS[@]}"; do
        MEMBER=$(echo "$MEMBER" | xargs)
        echo "   Adding IAP access: ${MEMBER}"
        gcloud run services add-iam-policy-binding "${SERVICE_NAME}" \
            --region="${REGION}" --project="${PROJECT_ID}" \
            --member="${MEMBER}" \
            --role="roles/iap.httpsResourceAccessor" --quiet
    done
fi

# Grant Cloud Run SA permission to invoke Cloud Run Jobs and services
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/run.invoker" --quiet 2>/dev/null || true
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/run.developer" --quiet 2>/dev/null || true

# ── Summary ──────────────────────────────────────────────────────────────────

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  ✅ Deployment Complete!"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "  Service URL:   ${SERVICE_URL}"
echo "  MCP Endpoint:  ${SERVICE_URL}/mcp"
echo "  Pipeline Job:  ${JOB_NAME}"
echo "  Auth:          ${AUTH_MODE}"
echo ""

if [ "$ENABLE_IAP" = true ]; then
    echo "  Add IAP users:"
    echo "    gcloud run services add-iam-policy-binding ${SERVICE_NAME} \\"
    echo "      --region=${REGION} --project=${PROJECT_ID} \\"
    echo "      --member='user:EMAIL' --role='roles/iap.httpsResourceAccessor'"
else
    echo "  Test with SA impersonation:"
    echo "    TOKEN=\$(gcloud auth print-identity-token \\"
    echo "      --audiences=${SERVICE_URL} \\"
    echo "      --impersonate-service-account=${SA_EMAIL} \\"
    echo "      --include-email)"
    echo ""
    echo "    curl -X POST ${SERVICE_URL}/mcp \\"
    echo "      -H \"Authorization: Bearer \$TOKEN\" \\"
    echo "      -H 'Content-Type: application/json' \\"
    echo "      -d '{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\",...}'"
    echo ""
    echo "  Run E2E tests:"
    echo "    uv run pytest mcp_server/tests/test_mcp_e2e.py -v \\"
    echo "      -k 'TestDiscovery or TestDatasetUpload' \\"
    echo "      --target=${SERVICE_URL}"
fi
echo "═══════════════════════════════════════════════════════════"
