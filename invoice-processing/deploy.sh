#!/bin/bash
set -e

PROJECT_ID="${1:?Usage: bash deploy.sh <PROJECT_ID> [REGION]}"
REGION="${2:-us-central1}"

echo "Deploying agent to project: $PROJECT_ID (region: $REGION)"

if [ -f setup.sh ]; then
    echo "Setting up GCP resources..."
    bash setup.sh "$PROJECT_ID" "$REGION"
fi

echo "Installing dependencies..."
uv sync
uv pip install google-agents-cli --python .venv/bin/python

echo "Deploying to Agent Engine..."
gcloud config set project "$PROJECT_ID"
GOOGLE_CLOUD_PROJECT="$PROJECT_ID" GOOGLE_CLOUD_LOCATION="$REGION" \
  .venv/bin/agents-cli deploy --project "$PROJECT_ID" --region "$REGION"

echo "Deployment complete!"
