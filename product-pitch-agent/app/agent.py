# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os

import google.auth
from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models.google_llm import Gemini
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import (
    StreamableHTTPConnectionParams,
)
from google.genai import types

from .instruction import DIRECTOR_INSTRUCTION
from .mcp_auth import make_authed_httpx_client_factory
from .llm import GeminiWithLocation
from .tools import (
    fetch_image_bytes,
    prepare_dataset,
    presign_video_url,
    report_job_progress,
    save_uploaded_file,
    wait_for_job,
)

_, project_id = google.auth.default()
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id)
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")

MCP_SERVER_URL = os.environ["MCP_SERVER_URL"].rstrip("/")

ads_video_mcp = McpToolset(
    connection_params=StreamableHTTPConnectionParams(
        url=f"{MCP_SERVER_URL}/mcp",
        timeout=30.0,
        sse_read_timeout=600.0,
        httpx_client_factory=make_authed_httpx_client_factory(MCP_SERVER_URL),
        terminate_on_close=False,
    ),
)

root_agent = Agent(
    name="product_pitch_director",
    model=GeminiWithLocation(
        model="gemini-3.5-flash",
        location="global",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=DIRECTOR_INSTRUCTION,
    generate_content_config=types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(include_thoughts=True),
    ),
    tools=[
        ads_video_mcp,
        wait_for_job,
        report_job_progress,
        fetch_image_bytes,
        presign_video_url,
        prepare_dataset,
        save_uploaded_file,
    ],
)

app = App(
    root_agent=root_agent,
    name="app",
)
