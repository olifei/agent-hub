# Agent Hub

Production-ready AI agent templates for Google Cloud Agent Engine.

## Deploy an Agent

```bash
git clone https://github.com/olifei/agent-hub
cd agent-hub/<agent-name>
bash deploy.sh <YOUR_PROJECT_ID>
```

## Available Agents

| Agent | Industry | Description |
|-------|----------|-------------|
| [blog-writer](blog-writer/) | Content | Technical blog writing with planning, editing, and social media |
| [customer-service](customer-service/) | Customer Support | Product selection, order management, and recommendations |
| [financial-advisor](financial-advisor/) | Finance | Investment insights, risk assessment, and portfolio management |
| [llm-auditor](llm-auditor/) | Technology | Fact-checking and verification of LLM-generated content |
| [travel-concierge](travel-concierge/) | Travel | Personalized travel planning with flights, hotels, and activities |
| [nurse-handover](nurse-handover/) | Healthcare | Structured nurse shift handover report generation |
| [academic-research](academic-research/) | Education | Academic topic exploration and research synthesis |

## For Agent Developers

Use the `/portal-ready` Claude Code skill to prepare your agent for this hub:

```bash
claude --add-dir /path/to/agent-hub
# then type: /portal-ready
```

The skill will generate `agent.yaml`, `deploy.sh`, and run `agents-cli scaffold enhance`.
