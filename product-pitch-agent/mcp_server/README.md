# MCP Server — Ads Video Generation Pipeline

MCP (Model Context Protocol) server that exposes the Ads Video Generation pipeline as tools and resources via Streamable HTTP transport.

## Architecture

```
                    ┌──────────────────────────────────┐
                    │         MCP Client               │
                    │  (Claude, Cline, custom app)      │
                    └──────────┬───────────────────────┘
                               │ Streamable HTTP (/mcp)
                               ▼
                    ┌──────────────────────────────────┐
                    │   Cloud Run Service (IAM)         │
                    │   MCP Server (server.py)          │
                    │   • list_products                 │
                    │   • batch_generate → dispatches   │
                    │   • get_job_status                │
                    │   • get_product_assets            │
                    └──────────┬───────────────────────┘
                               │ Cloud Run Jobs API
                               ▼
                    ┌──────────────────────────────────┐
                    │   Cloud Run Job                   │
                    │   Pipeline Runner                 │
                    │   • Gemini (image gen)             │
                    │   • Veo (video gen)                │
                    │   • Post-processing               │
                    └──────────┬───────────────────────┘
                               │ google-cloud-storage
                               ▼
                    ┌──────────────────────────────────┐
                    │   GCS Bucket (output)             │
                    └──────────────────────────────────┘
```

**Auth**: IAM-only (`--no-allow-unauthenticated`). Callers send a Google identity token in the `Authorization: Bearer <token>` header with the service URL as the audience. User identity is `anonymous` (no per-user job isolation).

**Execution**: MCP server is a lightweight dispatcher. Heavy pipeline work runs as Cloud Run Jobs (up to 1hr timeout, 4GB RAM, 2 vCPU). Job results land in GCS and are read back by `get_job_status` when the job completes.

**Resume behavior**: When `mode="full"` finds a prior `metadata.json` in GCS at `output/{product_id}/` whose `starting_frames.all_passed == true`, image generation is skipped and the run resumes from scene script + video. Useful for iterating on Veo without paying for image gen each time. Pass `force=True` to override.

## MCP Tools

| Tool | Description |
|---|---|
| `upload_dataset` | Import products from an Excel file (creates folders + metadata) |
| `list_products` | Discover product folders with metadata |
| `batch_generate` | Start async image/video generation job |
| `get_job_status` | Check job progress and results |
| `get_product_assets` | Get generated images, videos, metadata |
| `list_jobs` | List all jobs for current user |
| `cancel_job` | Cancel a running job |

## MCP Resources

| Resource URI | Description |
|---|---|
| `pipeline://config` | Current pipeline configuration |
| `pipeline://products/{data_dir}` | Product listing for a data directory |

## Dataset Upload (upload_dataset)

Product data is **not baked into the container image**. Instead, use the `upload_dataset` tool to import products from an Excel file at runtime.

### Excel Format

Each sheet becomes a product category subfolder. Required columns:

| Column | Required | Description |
|---|---|---|
| `product_id` | ✅ | Unique product identifier (becomes folder name) |
| `product_name` | ✅ | Product description used in ad copy generation |
| `country` | | Target country — full name or code (`US`, `United States`) |
| `language` | | Speech language — full name or code (`en`, `English`) |
| `image_url` | | Product image URL (auto-downloaded) |
| `company_name` | | Brand name per product (e.g. `Cymbal Shop`) |

### Example

A test dataset is included at `mcp_server/tests/test_dataset.xlsx`:

```
Sheet "Luggage Bags Cases":
  product_id     | product_name                        | country       | language | image_url     | company_name
  1600907870863  | Colorful Net Crochet Reusable Bag…  | United States | English  | https://…     | Cymbal Shop
  1601488769917  | PU Leather Keychain Bag…            | United States | English  | https://…     | Cymbal Shop

Sheet "Mother Kids Toys":
  1601524945369  | Sun and Moon Soft Plush Toy Pillows… | United States | English  | https://…     | Cymbal Shop
```

To regenerate it: `python mcp_server/tests/create_test_excel.py`

### Usage via MCP

```
upload_dataset(excel_path="mcp_server/tests/test_dataset.xlsx", data_dir="data")
→ Creates data/luggage_bags_cases/1600907870863/metadata.json + product_image.jpg
→ Creates data/luggage_bags_cases/1601488769917/metadata.json + product_image.jpg
→ Creates data/mother_kids_toys/1601524945369/metadata.json + product_image.jpg
```

Then run `batch_generate(data_dir="data")` to process them.

## Quick Start (Local)

`pyproject.toml` lives in `mcp_server/`, so dependency setup runs from there.
The package import path is `mcp_server.*`, so the server itself must be launched
from the **parent** directory.

```bash
# 1) Install deps into mcp_server/.venv
cd mcp_server
uv sync --extra test
cd ..

# 2) Run the server with the venv interpreter, from the repo root
mcp_server/.venv/bin/python -m mcp_server.server \
  --transport streamable-http --port 8080

# Or via stdio for local MCP clients
mcp_server/.venv/bin/python -m mcp_server.server --transport stdio
```

In local mode `EXECUTION_MODE` defaults to `local`, so `batch_generate` runs
the pipeline in a background thread inside the same process (no Cloud Run Jobs
API needed).

## Testing

The pytest suite supports both a local subprocess and a deployed URL via
`--target`. Identity tokens for deployed targets are minted via SA
impersonation.

```bash
# All commands run from the repo root, with the in-tree venv

# Discovery tests only (FREE — no API calls)
mcp_server/.venv/bin/pytest mcp_server/tests/test_mcp_e2e.py -v -k "TestDiscovery"

# Dataset upload + product listing (FREE — no Vertex AI calls)
mcp_server/.venv/bin/pytest mcp_server/tests/test_mcp_e2e.py -v -k "TestDatasetUpload"

# Image generation (~$0.10, ~4 min)
mcp_server/.venv/bin/pytest mcp_server/tests/test_mcp_e2e.py -v -k "image_only_single"

# Full pipeline — image + Veo + post-process (~$1-2, ~7 min once images are reused)
mcp_server/.venv/bin/pytest mcp_server/tests/test_mcp_e2e.py -v -k "full_single"
```

### Against the deployed Cloud Run service

When `--target` is a URL the conftest auto-detects the SA from the project
number embedded in the URL and runs `gcloud auth print-identity-token
--impersonate-service-account=...` per session. SA impersonation takes 1-2s; if
you're iterating, mint a token once and pass `--token` to skip it on each run
(tokens last 1 hour).

```bash
SVC_URL="https://ads-video-mcp-server-72273101339.us-central1.run.app"

# One-shot: let conftest mint the token via SA impersonation
mcp_server/.venv/bin/pytest mcp_server/tests/test_mcp_e2e.py -v \
  -k "TestDiscovery or TestDatasetUpload" \
  --target="$SVC_URL"

# Faster: pre-mint a 1-hour token and reuse it
TOKEN=$(gcloud auth print-identity-token \
  --audiences="$SVC_URL" \
  --impersonate-service-account=72273101339-compute@developer.gserviceaccount.com \
  --include-email)

mcp_server/.venv/bin/pytest mcp_server/tests/test_mcp_e2e.py -v \
  --target="$SVC_URL" --token="$TOKEN"
```

### Calling tools by hand with curl

The MCP Streamable HTTP transport requires an `initialize` round-trip to obtain
an `Mcp-Session-Id`, which must be sent on every subsequent request.

```bash
SVC_URL="https://ads-video-mcp-server-72273101339.us-central1.run.app"
TOKEN=$(gcloud auth print-identity-token \
  --audiences="$SVC_URL" \
  --impersonate-service-account=72273101339-compute@developer.gserviceaccount.com \
  --include-email)

# 1) Initialize (capture Mcp-Session-Id from response headers)
curl -sD /tmp/h.txt -X POST "$SVC_URL/mcp" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize",
       "params":{"protocolVersion":"2024-11-05","capabilities":{},
                 "clientInfo":{"name":"curl","version":"1"}}}' > /dev/null
SID=$(grep -i '^mcp-session-id:' /tmp/h.txt | awk '{print $2}' | tr -d '\r\n')

# 2) Send the initialized notification
curl -s -X POST "$SVC_URL/mcp" \
  -H "Authorization: Bearer $TOKEN" -H "Mcp-Session-Id: $SID" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized"}' > /dev/null

# 3) Call a tool (e.g. list_products)
curl -s -X POST "$SVC_URL/mcp" \
  -H "Authorization: Bearer $TOKEN" -H "Mcp-Session-Id: $SID" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call",
       "params":{"name":"list_products","arguments":{"data_dir":"data"}}}'
```

Tool responses arrive as SSE (`Content-Type: text/event-stream`); each `data:`
line is a JSON-RPC frame. See `mcp_server/tests/test_mcp_e2e.py:MCPTestClient`
for a reference parser.

### Typical end-to-end workflow

```text
1. upload_dataset(excel_path="gs://my-bucket/products.xlsx", data_dir="data")
2. list_products(data_dir="data")
3. batch_generate(mode="image_only", data_dir="data/<category>",
                  product_ids=["<pid>"], max_sample_images=1)
   → returns {job_id, status: "running"}
4. get_job_status(job_id)  # poll every ~10s until status == "completed"
5. get_product_assets(product_id="<pid>")
   → inspect generated_images / gcs_images
6. batch_generate(mode="full", data_dir="data/<category>",
                  product_ids=["<pid>"])
   # Reuses the image from step 3 (skips Step 1), runs Veo + post-process.
7. get_job_status(job_id)
8. get_product_assets(product_id="<pid>")
   → final_video / gcs_final_video
```

## Deploy to Google Cloud

### Prerequisites

- `gcloud` CLI authenticated
- GCP project with billing enabled
- Vertex AI API enabled

### Deploy

```bash
# Basic deployment
bash mcp_server/deploy.sh --project=my-project --region=us-central1

# With an explicit GCS bucket for output persistence
bash mcp_server/deploy.sh \
  --project=my-project --region=us-central1 \
  --bucket=my-output-bucket
```

The deploy script:
1. Enables required APIs (`run`, `compute`, `artifactregistry`, `cloudbuild`)
2. Creates the Artifact Registry repository (`mcp-server`)
3. Builds + pushes the container via `gcloud builds submit` driven by `cloudbuild.yaml`
4. Deploys the Cloud Run **Job** (pipeline runner, 4GB / 2 vCPU / 1h timeout)
5. Deploys the Cloud Run **Service** with `--no-allow-unauthenticated`
6. Grants the runtime service account `roles/run.invoker` and `roles/run.developer`

After deploy, grant invoke permission to additional users:

```bash
gcloud run services add-iam-policy-binding ads-video-mcp-server \
  --region=us-central1 --project=my-project \
  --member='user:alice@example.com' \
  --role='roles/run.invoker'
```

## File Structure

```
<repo root>
├── cloudbuild.yaml             # Cloud Build config (points at mcp_server/Dockerfile)
└── mcp_server/
    ├── __init__.py
    ├── server.py               # MCP server (FastMCP, tools, resources)
    ├── job_manager.py          # Thread-safe job tracking, user-scoped
    ├── cloud_run_jobs.py       # Cloud Run Jobs API integration
    ├── pipeline_runner.py      # Cloud Run Job entry point
    ├── pipeline/               # Pipeline code (self-contained)
    │   ├── orchestrator.py     # process_product / process_product_image_only
    │   ├── vertex_ai_service.py # Gemini + Veo + Imagen calls (uses ADC)
    │   ├── config.py
    │   ├── metadata.py
    │   └── ...
    ├── tests/
    │   ├── conftest.py         # Test config, --target / --token / --sa flags
    │   ├── test_mcp_e2e.py     # E2E tests (local + remote)
    │   ├── create_test_excel.py # Generate test_dataset.xlsx
    │   └── test_dataset.xlsx   # Sample dataset (3 products)
    ├── Dockerfile
    ├── deploy.sh               # One-command deploy
    ├── pyproject.toml
    └── README.md
```

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `EXECUTION_MODE` | `local` (threads) or `cloud_run_jobs` | `local` |
| `PIPELINE_JOB_NAME` | Cloud Run Job name for pipeline | `ads-video-pipeline-job` |
| `VERTEX_AI_PROJECT_ID` | GCP project for Vertex AI | — |
| `VERTEX_AI_LOCATION` | GCP region | `us-central1` |
| `GCS_BUCKET_NAME` | GCS bucket for output | — |
