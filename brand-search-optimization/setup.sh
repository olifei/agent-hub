#!/bin/bash
set -e

# --- Parse arguments ---
CLEANUP=false
POSITIONAL_ARGS=()
for arg in "$@"; do
  case $arg in
    --cleanup) CLEANUP=true ;;
    *) POSITIONAL_ARGS+=("$arg") ;;
  esac
done

PROJECT_ID="${POSITIONAL_ARGS[0]:?Usage: bash setup.sh <PROJECT_ID> [REGION] [--cleanup]}"
REGION="${POSITIONAL_ARGS[1]:-us-central1}"

DATASET_ID="products_data_agent"
TABLE_ID="shoe_items"

gcloud config set project "$PROJECT_ID"

if [ "$CLEANUP" = true ]; then
    echo "Cleaning up resources in project: $PROJECT_ID"
    bq rm -r -f -d "${PROJECT_ID}:${DATASET_ID}" 2>/dev/null && \
      echo "  Deleted dataset ${DATASET_ID}" || echo "  Dataset ${DATASET_ID} not found"
    echo "Cleanup complete."
    exit 0
fi

echo "============================================="
echo " Brand Search Optimization — Setup"
echo "============================================="
echo ""
echo "This will create the following paid GCP resources"
echo "in project: $PROJECT_ID"
echo ""
echo "  - BigQuery dataset: ${DATASET_ID}"
echo "  - BigQuery table:   ${DATASET_ID}.${TABLE_ID}"
echo ""
read -p "Continue? (y/N): " confirm
[ "$confirm" = "y" ] || exit 0

echo ""
echo "[1/3] Enabling APIs..."
gcloud services enable bigquery.googleapis.com

echo "[2/3] Creating BigQuery dataset and table..."
bq --location=US mk -d "${PROJECT_ID}:${DATASET_ID}" 2>/dev/null || echo "  Dataset already exists, skipping."
bq mk --table \
  "${PROJECT_ID}:${DATASET_ID}.${TABLE_ID}" \
  Title:STRING,Description:STRING,Attributes:STRING,Brand:STRING 2>/dev/null || echo "  Table already exists, skipping."

echo "[3/3] Loading seed data..."
bq query --use_legacy_sql=false --project_id="$PROJECT_ID" \
  "INSERT INTO \`${PROJECT_ID}.${DATASET_ID}.${TABLE_ID}\` (Title, Description, Attributes, Brand) VALUES
    ('Kids\\' Joggers', 'Comfortable and supportive running shoes for active kids. Breathable mesh upper keeps feet cool, while the durable outsole provides excellent traction.', 'Size: 10 Toddler, Color: Blue/Green', 'BSOAgentTestBrand'),
    ('Light-Up Sneakers', 'Fun and stylish sneakers with light-up features that kids will love. Supportive and comfortable for all-day play.', 'Size: 13 Toddler, Color: Silver', 'BSOAgentTestBrand'),
    ('School Shoes', 'Versatile and comfortable shoes perfect for everyday wear at school. Durable construction with a supportive design.', 'Size: 12 Preschool, Color: Black', 'BSOAgentTestBrand')"

echo ""
echo "============================================="
echo " Setup complete!"
echo "============================================="
echo ""
echo "Resource info (add to your .env):"
echo "  GOOGLE_CLOUD_PROJECT=${PROJECT_ID}"
echo "  GOOGLE_CLOUD_LOCATION=${REGION}"
echo "  DATASET_ID=${DATASET_ID}"
echo "  TABLE_ID=${TABLE_ID}"
echo "  GOOGLE_GENAI_USE_VERTEXAI=true"
