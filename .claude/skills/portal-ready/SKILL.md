---
name: portal-ready
description: Prepare an ADK agent project for Agent Portal. Generates agent.yaml metadata, scans for GCP dependencies, checks or generates setup.sh, and runs agents-cli scaffold enhance. Use when a developer wants to make their agent deployable via Agent Portal.
disable-model-invocation: true
allowed-tools: Bash(grep *) Bash(find *) Bash(cat *) Bash(ls *) Bash(uvx *)
---

# Prepare Agent for Portal

You are helping a developer prepare their ADK agent project for inclusion in the Agent Portal. Follow these steps in order. At each step, present your findings and ask the developer to confirm before proceeding.

## Step 1: Analyze the project

Read the project's README.md, pyproject.toml, and agent code to understand:
- What the agent does
- What industry it serves
- What tools and capabilities it has
- What the agent directory name is (the directory containing agent.py with root_agent)

If you cannot find an agent.py with a `root_agent` definition, stop and tell the developer this is required.

## Step 2: Generate agent.yaml

Based on your analysis, generate an `agent.yaml` file with these fields:

```yaml
name: <kebab-case name>
displayName: <human readable name>
description: <2-3 sentence description of what the agent does>
industry: <one of: content, customer-support, finance, technology, retail, healthcare, manufacturing, logistics, energy, telecom, education, government>
tags: <list of relevant tags>
```

Present the generated agent.yaml to the developer and ask them to confirm or suggest changes. Only write the file after confirmation.

## Step 3: Scan for GCP service dependencies

Scan ALL Python files in the project for usage of GCP services. Look for:

- `google.cloud.storage` or `gcs` references → **Cloud Storage**
- `google.cloud.bigquery` or `bigquery` references → **BigQuery**
- `google.cloud.firestore` or `firestore` references → **Firestore**
- `google.cloud.secretmanager` or `secret` references → **Secret Manager**
- `google.cloud.spanner` → **Spanner**
- `google.cloud.pubsub` → **Pub/Sub**
- `google.cloud.discoveryengine` or `vertex_ai_search` → **Vertex AI Search**
- `google.cloud.alloydb` or `alloydb` or `psycopg2` → **AlloyDB**
- MCP tool connections (MCPToolset, StreamableHTTPConnectionParams) → **MCP Server**
- A2A references (to_a2a, a2a_sdk) → **A2A Service**
- Environment variables referencing external API keys → **External APIs**

Also check `.env.example`, `.env`, config files, and seed data directories (CSV, SQL, JSON files) for service and data references.

Present your findings:

```
GCP Services detected:
  ✓ Cloud Storage — found in tools/data_loader.py
  ✓ BigQuery — found in agent.py, sub_agents/analyst.py

External dependencies:
  ✓ FRED_API_KEY — found in .env.example

Seed data:
  ✓ data/flights.csv — likely for BigQuery
```

Ask the developer: "Are there any services or data dependencies I missed?"

## Step 4: Check or generate setup.sh

Check if `setup.sh` exists in the project root.

### If setup.sh exists — validate it

Read the script and check against this checklist:

| Check | What to look for |
|-------|-----------------|
| PROJECT_ID parameterized | Accepts project ID as argument, no hardcoded project IDs |
| No sensitive info | No API keys, passwords, or secrets in the script |
| Dependency consistency | All GCP services detected in Step 3 have corresponding setup commands |
| API enablement | Has `gcloud services enable` for each required API |
| IAM roles | Sets up necessary Service Account roles |
| Cleanup support | Supports `--cleanup` flag to remove created resources |
| Error handling | Has `set -e` or equivalent error checking |
| Tool availability | Only uses tools available in Cloud Shell (gcloud, bq, gsutil, python3, etc.) |
| Data file references | All referenced seed data files exist in the repo |
| Environment variable output | Writes created resource info to `.env` or prints for user |
| Cost warning | Mentions that paid resources will be created |
| Idempotent | Handles already-existing resources gracefully (skip or update, not fail) |

Present results:

```
setup.sh validation:
  ✓ PROJECT_ID parameterized
  ✓ No sensitive info
  ✗ Missing API enablement for bigquery.googleapis.com
  ✗ No cleanup support
  ✓ Error handling (set -e)
  ...
```

Ask the developer to fix any issues found.

### If setup.sh does not exist

If GCP services or seed data were detected in Step 3, generate a `setup.sh` that:

- Accepts `PROJECT_ID` as first argument, `REGION` as optional second (default: us-central1)
- Supports `--cleanup` flag
- Has `set -e` for error handling
- Prints a cost warning at the start
- Enables required APIs
- Creates detected GCP resources (BigQuery datasets, GCS buckets, etc.)
- Loads seed data if present in the repo
- Sets up IAM roles
- Outputs resource info for `.env`
- Is idempotent

Follow this structure:

```bash
#!/bin/bash
set -e

# Parse arguments
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

if [ "$CLEANUP" = true ]; then
    echo "Cleaning up resources in project: $PROJECT_ID"
    # cleanup commands
    exit 0
fi

echo "This will create paid GCP resources in project: $PROJECT_ID"
read -p "Continue? (y/N): " confirm
[ "$confirm" = "y" ] || exit 0

echo "[1/N] Enabling APIs..."
echo "[2/N] Creating resources..."
echo "[3/N] Loading seed data..."
echo "[4/N] Setting up IAM..."

echo "Done! Resource info:"
echo "  DATASET_ID=..."
echo "  BUCKET_NAME=..."
```

Present the generated setup.sh and ask the developer to confirm before writing.

If no GCP services or data dependencies were detected, skip this step.

## Step 5: Ensure pyproject.toml has ASP configuration

Check if pyproject.toml contains `[tool.agent-starter-pack]`. If not, add:

```toml
[tool.agent-starter-pack]
base_template = "adk"

[tool.agent-starter-pack.settings]
agent_directory = "<detected_agent_directory>"
deployment_targets = ["agent_engine"]
```

Show the developer what will be added and confirm.

## Step 6: Run agents-cli scaffold enhance

Run the following command to add deployment infrastructure:

```bash
uvx google-agents-cli scaffold enhance --agent-directory <agent_dir> --deployment-target agent_runtime -s --yes
```

Show the output to the developer.

## Step 7: Generate deploy.sh

Create a `deploy.sh` in the project root that customers use for one-click deployment:

```bash
#!/bin/bash
set -e

PROJECT_ID="${1:?Usage: bash deploy.sh <PROJECT_ID> [REGION]}"
REGION="${2:-us-central1}"

echo "Deploying agent to project: $PROJECT_ID (region: $REGION)"

# Create GCP resources if setup.sh exists
if [ -f setup.sh ]; then
    echo "Setting up GCP resources..."
    bash setup.sh "$PROJECT_ID" "$REGION"
fi

# Install dependencies and deploy
echo "Installing dependencies..."
make install

echo "Deploying to Agent Engine..."
GOOGLE_CLOUD_PROJECT="$PROJECT_ID" GOOGLE_CLOUD_LOCATION="$REGION" make backend

echo "Deployment complete!"
```

Present to developer and confirm before writing.

## Step 8: Verify

After all steps are complete, verify the project structure:

```bash
ls agent.yaml
ls deploy.sh
ls <agent_dir>/agent.py
grep "root_agent" <agent_dir>/agent.py
grep "agent-starter-pack" pyproject.toml
```

Present a summary:

```
✓ agent.yaml — metadata for Portal
✓ deploy.sh — one-click deployment script
✓ agent.py — has root_agent
✓ pyproject.toml — has ASP config
✓ setup.sh — resource setup script (if applicable)
✓ agents-cli enhance — deployment files added

Your agent is ready for Agent Portal!

Customer deployment flow:
  git clone https://github.com/olifei/agent-hub
  cd agent-hub/<agent-name>
  bash deploy.sh <PROJECT_ID>

Next: submit a PR to https://github.com/olifei/agent-hub
```
