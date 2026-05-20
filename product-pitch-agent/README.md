# Product Pitch Director Agent

A conversational agent that turns a product catalog into ad images and videos, by orchestrating an Ads Video Generation pipeline (Gemini image gen + Veo video gen + Gemini evaluators).

The agent is published to **Gemini Enterprise** as **Product Pitch Director** and runs on Vertex AI **Agent Runtime**. Heavy generation work runs in a separate MCP server on **Cloud Run** (dispatcher) + **Cloud Run Jobs** (pipeline execution).

## Architecture

```
User ── chat ──▶ Gemini Enterprise (Product Pitch Director)
                       │
                       │ ADK agent on Agent Runtime
                       ▼
              ┌──────────────────────────────────┐
              │  Product Pitch Director agent    │   agent/
              │  (single LlmAgent, gemini-flash) │
              └──────────────┬───────────────────┘
                             │ MCPToolset (Streamable HTTP, IAM-only)
                             ▼
              ┌──────────────────────────────────┐
              │  Ads Video MCP Server            │   mcp_server/
              │  Cloud Run service (dispatcher)  │
              └──────────────┬───────────────────┘
                             │ Cloud Run Jobs API
                             ▼
              ┌──────────────────────────────────┐
              │  Pipeline Runner (Cloud Run Job) │
              │  Gemini image gen + Veo video    │
              │  gen + Gemini evaluators         │
              └──────────────┬───────────────────┘
                             │
                             ▼
                       GCS output bucket
```

## Repository Layout

| Path | What lives here |
|---|---|
| `agent/` | ADK agent (`product_pitch_director`) deployed to Agent Runtime. See [`agent/README.md`](agent/README.md). |
| `mcp_server/` | MCP server + pipeline runner deployed to Cloud Run. See [`mcp_server/README.md`](mcp_server/README.md). |
| `cloudbuild.yaml` | Cloud Build config for the MCP server container. |
| `example_dataset.xlsx`, `product_pitch_flow_demo_dataset.xlsx` | Sample input catalogs. |

## Quick Start

### 1. Deploy the MCP server (Cloud Run)

```bash
bash mcp_server/deploy.sh \
  --project=<your-project> \
  --region=us-central1 \
  --bucket=<your-output-bucket>
```

This builds the container, deploys the Cloud Run service (IAM-only) and the Cloud Run Job (pipeline runner), and wires up the necessary IAM bindings. Note the service URL it prints — you'll need it for the agent.

For the agent's MCP cold-start latency, keep one instance warm:

```bash
gcloud run services update ads-video-mcp-server \
  --region=us-central1 --min-instances=1
```

### 2. Deploy the agent (Agent Runtime)

```bash
cd agent
agents-cli install

# Set MCP server URL the agent will call
export MCP_SERVER_URL=https://<your-mcp-server-url>
export GCS_BUCKET_NAME=<your-output-bucket>

agents-cli deploy
```

This deploys the ADK agent to Vertex AI Agent Runtime and writes `agent/deployment_metadata.json`.

### 3. Publish to Gemini Enterprise

```bash
cd agent

agents-cli publish gemini-enterprise \
  --gemini-enterprise-app-id projects/<project>/locations/global/collections/default_collection/engines/<engine-id> \
  --display-name "Product Pitch Director" \
  --description "Turns a product catalog into ad images and videos" \
  --tool-description "Generates product ad images and videos from a catalog (Excel/CSV/JSON in GCS or product list in chat). Iterates with the user on review and approval before generating videos."
```

The Gemini Enterprise app must already exist (create it in Cloud Console → Gemini Enterprise → Apps).

## Local Development

### Agent

```bash
cd agent
agents-cli install
export MCP_SERVER_URL=https://<your-mcp-server-url>   # or a local one
agents-cli playground
```

See [`agent/README.md`](agent/README.md) for the full set of `agents-cli` commands (lint, test, deploy, scaffold enhance, etc.).

### MCP server

```bash
cd mcp_server
uv sync --extra test
cd ..
mcp_server/.venv/bin/python -m mcp_server.server --transport streamable-http --port 8080
```

In local mode (`EXECUTION_MODE=local`, default), `batch_generate` runs the pipeline in-process — no Cloud Run Jobs API required.

## Typical Flow (UC1 from DESIGN_SPEC)

```text
1. User uploads a catalog: "Here's our spring catalog: gs://acme/spring2026.xlsx"
2. Agent: upload_dataset → list_products → batch_generate(mode=image_only)
3. Agent: report_job_progress + wait_for_job → notifies on completion
4. Agent: get_product_assets, reads starting_frames.evaluation_results,
         retries failed criteria up to 2x, shows GCS URIs to user
5. User approves → batch_generate(mode=full) → Veo + post-process
6. Agent: get_product_assets, returns final_video URIs with criteria summary
```

## Required GCP Setup

- Vertex AI API enabled
- Cloud Run + Cloud Run Jobs APIs enabled
- Artifact Registry repository `mcp-server`
- GCS bucket for pipeline output
- Service account with `roles/run.invoker`, `roles/run.developer`, `roles/aiplatform.user`, `roles/storage.objectAdmin`
- A Gemini Enterprise app for publishing
