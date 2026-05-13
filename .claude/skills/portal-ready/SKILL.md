---
name: portal-ready
description: Prepare an ADK agent project for Agent Portal. Generates agent.yaml metadata, scans for GCP service dependencies, generates Terraform configs, and runs agents-cli scaffold enhance. Use when a developer wants to make their agent deployable via Agent Portal.
disable-model-invocation: true
allowed-tools: Bash(grep *) Bash(find *) Bash(cat *) Bash(ls *) Bash(uvx *) Bash(agents-cli *)
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
- MCP tool connections (MCPToolset, StreamableHTTPConnectionParams) → **MCP Server**
- A2A references (to_a2a, a2a_sdk) → **A2A Service**
- Environment variables referencing external API keys → **External APIs**

Also check `.env.example`, `.env`, and any config files for service references.

Present your findings as a list:

```
GCP Services detected:
  ✓ Cloud Storage — found in tools/data_loader.py
  ✓ BigQuery — found in agent.py, sub_agents/analyst.py

External dependencies:
  ✓ FRED_API_KEY — found in .env.example

No Terraform configuration found in deployment/terraform/.
```

Ask the developer: "Are there any services I missed? Please add or remove from this list."

## Step 4: Generate Terraform configurations

If GCP services were identified in Step 3, generate Terraform configurations in `deployment/terraform/`.

For each service, create the appropriate `.tf` file following ASP conventions:

- **Cloud Storage**: Create bucket resource
- **BigQuery**: Create dataset and table resources
- **Firestore**: Create database resource
- **Secret Manager**: Create secret resources for each API key
- **IAM**: Create service account bindings for all required services

Use variables for project_id, region, and project_name. Follow this pattern:

```hcl
variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region"
  type        = string
  default     = "us-central1"
}

variable "project_name" {
  description = "Project name for resource naming"
  type        = string
}
```

Present the generated Terraform files to the developer and ask them to confirm before writing.

If no GCP services were found, skip this step.

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

## Step 7: Verify

After all steps are complete, verify the project structure:

```bash
# Check required files exist
ls agent.yaml
ls <agent_dir>/agent.py
grep "root_agent" <agent_dir>/agent.py
grep "agent-starter-pack" pyproject.toml
```

Present a summary:

```
✓ agent.yaml — metadata for Portal
✓ agent.py — has root_agent
✓ pyproject.toml — has ASP config
✓ deployment/terraform/ — resource declarations (if applicable)
✓ agents-cli enhance — deployment files added

Your agent is ready for Agent Portal!
Next: submit a PR to https://github.com/cloud-gtm/agent-portal-templates
```
