# MCP Server for Ads Video Generation Pipeline
# Deployed to Cloud Run with explicit GCS API uploads for data persistence

FROM python:3.11-slim

# Install system dependencies (ffmpeg for moviepy video processing)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy the entire project (mcp_server imports from mcp_server.pipeline.*)
COPY mcp_server/pyproject.toml ./pyproject.toml
COPY mcp_server/ mcp_server/

# Data is uploaded at runtime via the upload_dataset tool — not baked into image

# Install dependencies
RUN uv sync --frozen --no-dev 2>/dev/null || uv pip install --system \
    "mcp[cli]>=1.9.0" \
    "pydantic-settings>=2.0" \
    "google-cloud-aiplatform>=1.60.0" \
    "google-cloud-storage>=2.14.0" \
    "google-cloud-secret-manager>=2.20.0" \
    "google-genai>=1.0.0" \
    "loguru>=0.7.0" \
    "Pillow>=10.0" \
    "moviepy>=2.0" \
    "httpx>=0.27" \
    "openpyxl>=3.1" \
    "pandas>=2.0" \
    "requests>=2.31"

# Install extra dependencies not in uv.lock
RUN uv pip install --system \
    "google-cloud-secret-manager>=2.20.0" \
    "google-cloud-run>=0.10.0" \
    "google-cloud-logging>=3.10.0" \
    "pandas>=2.0" \
    "openpyxl>=3.1" \
    "requests>=2.31" \
    2>/dev/null || true

# Create output directory
RUN mkdir -p output_v2 temp/logs

# Cloud Run uses PORT env var
ENV PORT=8080

EXPOSE 8080

# Run MCP server with Streamable HTTP transport
CMD ["python", "-m", "mcp_server.server", "--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8080"]
