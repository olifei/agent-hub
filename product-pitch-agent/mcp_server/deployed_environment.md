# Deployed Cloud Run Environment Reference

> Last updated: 2026-05-12

## Project

| Field | Value |
|---|---|
| **Project ID** | `jingyiwa-project-445909` |
| **Project Number** | `72273101339` |
| **Region** | `us-central1` |
| **Active gcloud account** | `admin@jingyiwa.altostrat.com` |

---

## Cloud Run Service (MCP Server)

| Field | Value |
|---|---|
| **Service Name** | `ads-video-mcp-server` |
| **URL (new format)** | `https://ads-video-mcp-server-72273101339.us-central1.run.app` |
| **URL (legacy format)** | `https://ads-video-mcp-server-jbq2nkjsxa-uc.a.run.app` |
| **MCP Endpoint** | `<service-url>/mcp` |
| **Image** | `us-central1-docker.pkg.dev/jingyiwa-project-445909/mcp-server/ads-video-mcp-server:latest` |
| **Image Digest** | `sha256:193037f5...` (built 2026-05-11) |
| **Revision** | `ads-video-mcp-server-00013-zpk` |
| **CPU / Memory** | 1 vCPU / 1Gi |
| **Concurrency** | 20 |
| **Max Instances** | 3 |
| **Timeout** | 60s |
| **Auth** | `--no-allow-unauthenticated` (requires identity token) |
| **Service Account** | `72273101339-compute@developer.gserviceaccount.com` |

### Service Environment Variables

| Variable | Value |
|---|---|
| `VERTEX_AI_PROJECT_ID` | `jingyiwa-project-445909` |
| `VERTEX_AI_LOCATION` | `us-central1` |
| `VERTEX_AI_PREVIEW_LOCATION` | `global` |
| `GCS_PREFIX` | `mcp-pipeline` |
| `EXECUTION_MODE` | `cloud_run_jobs` |
| `PIPELINE_JOB_NAME` | `ads-video-pipeline-job` |
| `GCS_BUCKET_NAME` | `jingyiwa-product-pitch-flow` |

---

## Cloud Run Job (Pipeline Runner)

| Field | Value |
|---|---|
| **Job Name** | `ads-video-pipeline-job` |
| **Command** | `python -m mcp_server.pipeline_runner` |
| **Image** | Same as service (`ads-video-mcp-server:latest`) |
| **CPU / Memory** | 2 vCPU / 4Gi |
| **Timeout** | 3600s (1 hour) |
| **Max Retries** | 1 |
| **Execution Environment** | gen2 |
| **Service Account** | `72273101339-compute@developer.gserviceaccount.com` |
| **Total Executions** | 3 (latest: `ads-video-pipeline-job-5f5cx`, succeeded) |

### Job Environment Variables

| Variable | Value |
|---|---|
| `VERTEX_AI_PROJECT_ID` | `jingyiwa-project-445909` |
| `VERTEX_AI_LOCATION` | `us-central1` |
| `VERTEX_AI_PREVIEW_LOCATION` | `global` |
| `GCS_PREFIX` | `mcp-pipeline` |
| `GCS_BUCKET_NAME` | `jingyiwa-product-pitch-flow` |

---

## IAM Permissions

### Service-level (on `ads-video-mcp-server`)

| Member | Role |
|---|---|
| `user:admin@jingyiwa.altostrat.com` | `roles/run.invoker` |

### Project-level (on `jingyiwa-project-445909`)

| Member | Role |
|---|---|
| `serviceAccount:72273101339-compute@developer.gserviceaccount.com` | `roles/run.invoker` |
| `serviceAccount:72273101339-compute@developer.gserviceaccount.com` | `roles/run.developer` |

---