#!/bin/bash
set -e

# =============================================================================
# Product Pitch Agent — GCP Resource Setup
#
# Creates: GCS bucket, Artifact Registry repo, enables APIs, sets IAM
#
# Usage:
#   bash setup.sh <PROJECT_ID> [REGION]
#   bash setup.sh <PROJECT_ID> [REGION] --cleanup
#
# WARNING: This script creates paid GCP resources.
# =============================================================================

CLEANUP=false
POSITIONAL=()
for arg in "$@"; do
  case $arg in
    --cleanup) CLEANUP=true ;;
    *) POSITIONAL+=("$arg") ;;
  esac
done

PROJECT_ID="${POSITIONAL[0]:?Usage: bash setup.sh <PROJECT_ID> [REGION] [--cleanup]}"
REGION="${POSITIONAL[1]:-us-central1}"

BUCKET_NAME="${PROJECT_ID}-pitch-agent-output"
AR_REPO="mcp-server"

gcloud config set project "$PROJECT_ID"
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
SA_EMAIL="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

# ---- Cleanup ----
if [ "$CLEANUP" = true ]; then
    echo "Cleaning up Product Pitch Agent resources..."
    gsutil rm -r "gs://${BUCKET_NAME}" 2>/dev/null || echo "  Bucket not found."
    gcloud run services delete ads-video-mcp-server --region="$REGION" --quiet 2>/dev/null || echo "  Service not found."
    gcloud run jobs delete ads-video-pipeline-job --region="$REGION" --quiet 2>/dev/null || echo "  Job not found."
    echo "Cleanup complete."
    exit 0
fi

echo "=== Product Pitch Agent Setup ==="
echo "Project:  $PROJECT_ID ($PROJECT_NUMBER)"
echo "Region:   $REGION"
echo "Bucket:   $BUCKET_NAME"
echo ""
echo "This will create:"
echo "  - GCS bucket for pipeline output"
echo "  - Artifact Registry repo for container images"
echo "  - Enable Cloud Run, Vertex AI, and other APIs"
echo "  - Set IAM roles for compute service account"
echo ""
echo "WARNING: This creates paid GCP resources."
echo ""

# ---- APIs ----
echo "[1/4] Enabling APIs..."
gcloud services enable \
    run.googleapis.com \
    compute.googleapis.com \
    artifactregistry.googleapis.com \
    cloudbuild.googleapis.com \
    aiplatform.googleapis.com \
    storage.googleapis.com \
    --project="$PROJECT_ID" --quiet

# ---- GCS Bucket ----
echo "[2/4] Creating GCS bucket..."
if gsutil ls -b "gs://${BUCKET_NAME}" &>/dev/null; then
    echo "  Bucket already exists, skipping."
else
    gsutil mb -p "$PROJECT_ID" -l "$REGION" "gs://${BUCKET_NAME}"
    echo "  Bucket created."
fi

# ---- Artifact Registry ----
echo "[3/4] Creating Artifact Registry repo..."
gcloud artifacts repositories describe "$AR_REPO" \
    --project="$PROJECT_ID" --location="$REGION" \
    --format="value(name)" 2>/dev/null || \
gcloud artifacts repositories create "$AR_REPO" \
    --project="$PROJECT_ID" --location="$REGION" \
    --repository-format=docker --description="MCP Server images"

# ---- IAM ----
echo "[4/4] Setting IAM roles..."
for role in roles/run.invoker roles/run.developer roles/aiplatform.user roles/storage.objectAdmin; do
    gcloud projects add-iam-policy-binding "$PROJECT_ID" \
        --member="serviceAccount:${SA_EMAIL}" \
        --role="$role" --quiet 2>/dev/null || true
done
echo "  IAM roles configured."

# ---- Output ----
echo ""
echo "=== Setup complete ==="
echo ""
echo "Resource info (used by deploy.sh):"
echo "  GCS_BUCKET_NAME=${BUCKET_NAME}"
echo "  REGION=${REGION}"
echo ""
echo "Next: bash deploy.sh $PROJECT_ID $REGION"
