#!/bin/bash
set -e

# =============================================================================
# YouTube Analyst — GCP Resource Setup
# Creates: GCS bucket for public artifact publishing
# Enables: Required Google Cloud APIs
#
# Usage:
#   bash setup.sh <PROJECT_ID> [REGION]
#   bash setup.sh <PROJECT_ID> [REGION] --cleanup
#
# WARNING: This script creates paid GCP resources. You may incur charges.
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

BUCKET_NAME="${PROJECT_ID}-youtube-analyst-artifacts"

gcloud config set project "$PROJECT_ID"

# ---- Cleanup mode ----
if [ "$CLEANUP" = true ]; then
    echo "Cleaning up YouTube Analyst resources..."
    echo "Deleting GCS bucket: gs://${BUCKET_NAME}"
    gsutil rm -r "gs://${BUCKET_NAME}" 2>/dev/null || echo "  Bucket not found, skipping."
    echo "Cleanup complete."
    exit 0
fi

echo "=== YouTube Analyst Setup ==="
echo "Project:  $PROJECT_ID"
echo "Region:   $REGION"
echo "WARNING: This script creates paid GCP resources."
echo ""

# ---- Enable APIs ----
echo "Enabling required APIs..."
gcloud services enable \
    aiplatform.googleapis.com \
    storage.googleapis.com \
    youtube.googleapis.com \
    --project="$PROJECT_ID"

# ---- Create GCS Bucket ----
echo "Creating GCS bucket for public artifacts: gs://${BUCKET_NAME}"
if gsutil ls -b "gs://${BUCKET_NAME}" &>/dev/null; then
    echo "  Bucket already exists, skipping."
else
    gsutil mb -p "$PROJECT_ID" -l "$REGION" "gs://${BUCKET_NAME}"
    echo "  Bucket created."
fi

# ---- Write .env ----
echo ""
echo "Writing resource info to .env..."
cat > .env <<EOF
GOOGLE_CLOUD_PROJECT=${PROJECT_ID}
GOOGLE_CLOUD_LOCATION=global
GOOGLE_GENAI_USE_VERTEXAI=1
PUBLIC_ARTIFACT_BUCKET=${BUCKET_NAME}
EOF

echo ""
echo "=== Setup complete ==="
echo "Resources created:"
echo "  GCS Bucket: gs://${BUCKET_NAME}"
echo ""
echo "Next steps:"
echo "  1. Get a YouTube Data API v3 key: https://developers.google.com/youtube/v3/getting-started"
echo "  2. The agent will prompt you for the key during your first interaction."
