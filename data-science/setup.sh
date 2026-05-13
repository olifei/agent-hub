#!/bin/bash
set -e

PROJECT_ID="${1:?Usage: bash setup.sh <PROJECT_ID> [REGION] [DATASET]}"
REGION="${2:-us-central1}"
DATASET="${3:-forecasting_sticker_sales}"

# --- Cleanup mode ---
if [ "$1" = "--cleanup" ] || [ "$2" = "--cleanup" ] || [ "$3" = "--cleanup" ]; then
    PROJECT_ID="${PROJECT_ID/--cleanup/}"
    PROJECT_ID="${PROJECT_ID:-$2}"
    PROJECT_ID="${PROJECT_ID:?Usage: bash setup.sh --cleanup <PROJECT_ID>}"
    echo "Cleaning up resources in project: $PROJECT_ID"

    echo "Deleting BigQuery dataset '$DATASET'..."
    bq rm -r -f --project_id="$PROJECT_ID" "$DATASET" 2>/dev/null || echo "  Dataset '$DATASET' not found or already deleted."

    echo "Deleting Vertex AI RAG corpora named 'bqml_referenceguide_corpus'..."
    # RAG corpus cleanup requires Python/API; print instructions
    echo "  To delete RAG corpora, run:"
    echo "    python3 -c \"import vertexai; from vertexai import rag; vertexai.init(project='$PROJECT_ID', location='$REGION'); [rag.delete_corpus(c.name) for c in rag.list_corpora() if c.display_name == 'bqml_referenceguide_corpus']\""

    echo "Cleanup complete."
    exit 0
fi

echo "============================================================"
echo " Data Science Agent — GCP Resource Setup"
echo "============================================================"
echo ""
echo " Project:  $PROJECT_ID"
echo " Region:   $REGION"
echo " Dataset:  $DATASET"
echo ""
echo " This script will create the following paid GCP resources:"
echo "   - BigQuery dataset with seed data"
echo "   - Vertex AI RAG corpus (for BQML reference guide)"
echo ""
echo " Estimated cost: minimal (BigQuery free tier covers small"
echo " datasets; RAG corpus has no idle cost)."
echo ""
read -p "Continue? (y/N): " confirm
[ "$confirm" = "y" ] || [ "$confirm" = "Y" ] || exit 0

# --- Step 1: Enable APIs ---
echo ""
echo "[1/4] Enabling APIs..."
gcloud services enable \
    bigquery.googleapis.com \
    aiplatform.googleapis.com \
    compute.googleapis.com \
    cloudresourcemanager.googleapis.com \
    --project="$PROJECT_ID" \
    --quiet

echo "  APIs enabled."

# --- Step 2: Create BigQuery dataset and load seed data ---
echo ""
echo "[2/4] Creating BigQuery dataset and loading seed data..."

# Create dataset (idempotent — skips if exists)
if bq show --project_id="$PROJECT_ID" "$DATASET" > /dev/null 2>&1; then
    echo "  Dataset '$DATASET' already exists, skipping creation."
else
    bq mk --location="$REGION" --dataset "$PROJECT_ID:$DATASET"
    echo "  Dataset '$DATASET' created."
fi

if [ "$DATASET" = "forecasting_sticker_sales" ]; then
    echo "  Loading forecasting_sticker_sales seed data..."
    bq --project_id="$PROJECT_ID" --location="$REGION" \
        load --source_format=CSV --autodetect --skip_leading_rows=1 --replace \
        "$DATASET.train" data_science/utils/data/train.csv
    bq --project_id="$PROJECT_ID" --location="$REGION" \
        load --source_format=CSV --autodetect --skip_leading_rows=1 --replace \
        "$DATASET.test" data_science/utils/data/test.csv
    echo "  Seed data loaded (train, test)."

elif [ "$DATASET" = "flights_dataset" ]; then
    echo "  Loading flights_dataset seed data..."
    bq --project_id="$PROJECT_ID" --location="$REGION" \
        load --source_format=CSV --autodetect --skip_leading_rows=1 --replace \
        "$DATASET.flight_history" flights_dataset/flight_history_table.csv
    bq --project_id="$PROJECT_ID" --location="$REGION" \
        load --source_format=CSV --autodetect --skip_leading_rows=1 \
        --allow_quoted_newlines --replace \
        "$DATASET.cymbalair_policies" flights_dataset/cymbalair_policies_table.csv
    bq --project_id="$PROJECT_ID" --location="$REGION" \
        load --source_format=CSV --autodetect --skip_leading_rows=1 --replace \
        "$DATASET.ticket_sales_history" flights_dataset/ticket_sales_history_table.csv
    echo "  Seed data loaded (flight_history, cymbalair_policies, ticket_sales_history)."
    echo ""
    echo "  NOTE: The flights_dataset also requires AlloyDB for full functionality."
    echo "  See README.md for AlloyDB setup instructions."
else
    echo "  Custom dataset '$DATASET' — no seed data to load."
fi

# --- Step 3: Create Vertex AI RAG corpus for BQML ---
echo ""
echo "[3/4] Setting up Vertex AI RAG corpus for BQML agent..."

export GOOGLE_CLOUD_PROJECT="$PROJECT_ID"
export GOOGLE_CLOUD_LOCATION="$REGION"
export BQ_DATA_PROJECT_ID="$PROJECT_ID"
export BQ_COMPUTE_PROJECT_ID="$PROJECT_ID"
export BQ_DATASET_ID="$DATASET"
export BQML_RAG_CORPUS_NAME=""

python3 data_science/utils/reference_guide_RAG.py
echo "  RAG corpus created. Check .env for BQML_RAG_CORPUS_NAME."

# --- Step 4: Set up IAM roles ---
echo ""
echo "[4/4] Setting up IAM roles..."

PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
RE_SA="service-${PROJECT_NUMBER}@gcp-sa-aiplatform-re.iam.gserviceaccount.com"

for role in roles/bigquery.user roles/bigquery.dataViewer roles/aiplatform.user; do
    gcloud projects add-iam-policy-binding "$PROJECT_ID" \
        --member="serviceAccount:${RE_SA}" \
        --condition=None \
        --role="$role" \
        --quiet 2>/dev/null || echo "  Note: Could not bind $role (service agent may not exist yet)."
done

echo "  IAM roles configured for Reasoning Engine service agent."

# --- Done ---
echo ""
echo "============================================================"
echo " Setup complete!"
echo "============================================================"
echo ""
echo " Add these to your .env file:"
echo ""
echo "   GOOGLE_GENAI_USE_VERTEXAI=1"
echo "   GOOGLE_CLOUD_PROJECT=$PROJECT_ID"
echo "   GOOGLE_CLOUD_LOCATION=$REGION"
echo "   BQ_DATA_PROJECT_ID=$PROJECT_ID"
echo "   BQ_COMPUTE_PROJECT_ID=$PROJECT_ID"
echo "   BQ_DATASET_ID=$DATASET"
echo ""
if [ "$DATASET" = "forecasting_sticker_sales" ]; then
    echo "   DATASET_CONFIG_FILE=./forecasting_sticker_sales_dataset_config.json"
elif [ "$DATASET" = "flights_dataset" ]; then
    echo "   DATASET_CONFIG_FILE=./flights_dataset_config.json"
fi
echo ""
echo " To clean up resources later:"
echo "   bash setup.sh --cleanup $PROJECT_ID"
echo ""
