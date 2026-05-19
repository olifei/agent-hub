# Copyright 2025 Google LLC
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

"""
User context for multi-tenant output isolation.

Uses a threading-local variable to hold the current user_id so that
all pipeline modules can scope their output paths (local and GCS)
by user without requiring user_id in every function signature.

Usage:
    from mcp_server.pipeline.user_context import set_user_id, get_output_base_dir, get_gcs_prefix

    # At entry point (server.py / pipeline_runner.py):
    set_user_id("user@example.com")

    # In pipeline modules — replaces settings.TEMP_OUTPUT_DIR:
    base_dir = get_output_base_dir()   # e.g. "output_mcp/user@example.com"

    # In pipeline modules — replaces settings.GCS_PREFIX:
    prefix = get_gcs_prefix()          # e.g. "pipeline/user@example.com"
"""

import threading

from mcp_server.pipeline.config import settings

# Thread-local storage for user_id (works with ThreadPoolExecutor threads)
_local = threading.local()


def set_user_id(user_id: str) -> None:
    """Set the current user_id for this thread.

    Args:
        user_id: The user identifier (e.g. email from IAP header).
                 Use "anonymous" for local/CLI usage.
    """
    _local.user_id = user_id


def get_user_id() -> str:
    """Get the current user_id for this thread.

    Returns:
        The user_id if set, or "anonymous" as fallback.
    """
    return getattr(_local, "user_id", "anonymous")


def get_output_base_dir() -> str:
    """Return the user-scoped local output base directory.

    When a user_id is set (and is not "anonymous"), returns:
        {settings.TEMP_OUTPUT_DIR}/{user_id}
    Otherwise returns:
        {settings.TEMP_OUTPUT_DIR}

    This replaces direct use of ``settings.TEMP_OUTPUT_DIR`` in pipeline modules.
    """
    user_id = get_user_id()
    if user_id and user_id != "anonymous":
        return f"{settings.TEMP_OUTPUT_DIR}/{user_id}"
    return settings.TEMP_OUTPUT_DIR


def get_gcs_prefix() -> str:
    """Return the user-scoped GCS prefix.

    When a user_id is set (and is not "anonymous"), returns:
        {settings.GCS_PREFIX}/{user_id}
    Otherwise returns:
        {settings.GCS_PREFIX}

    This replaces direct use of ``settings.GCS_PREFIX`` in pipeline modules.
    """
    user_id = get_user_id()
    if user_id and user_id != "anonymous":
        return f"{settings.GCS_PREFIX}/{user_id}"
    return settings.GCS_PREFIX
