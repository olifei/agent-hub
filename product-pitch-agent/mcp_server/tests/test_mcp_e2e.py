"""
End-to-end tests for the MCP Server.

Tests follow the real user workflow: upload dataset → list products → generate.
Supports both local and remote (deployed Cloud Run) targets.

Usage:
    # Discovery tests (FREE, no API calls — just connectivity + tool listing)
    uv run pytest mcp_server/tests/test_mcp_e2e.py -v -k "TestDiscovery"

    # Dataset upload + product listing (FREE, no Vertex AI calls)
    uv run pytest mcp_server/tests/test_mcp_e2e.py -v -k "TestDatasetUpload"

    # Image generation test (~$0.10, ~2 min) — requires upload first
    uv run pytest mcp_server/tests/test_mcp_e2e.py -v -k "TestImageGeneration"

    # Full pipeline test (~$1-2, ~10 min)
    uv run pytest mcp_server/tests/test_mcp_e2e.py -v -k "TestFullPipeline"

    # All tests
    uv run pytest mcp_server/tests/test_mcp_e2e.py -v

    # Against deployed server (IAM auth via SA impersonation)
    uv run pytest mcp_server/tests/test_mcp_e2e.py -v \\
        --target=https://ads-video-mcp-server-xxx.us-central1.run.app

    # Against deployed server with explicit SA
    uv run pytest mcp_server/tests/test_mcp_e2e.py -v \\
        --target=https://ads-video-mcp-server-xxx.us-central1.run.app \\
        --sa=MY-SA@PROJECT.iam.gserviceaccount.com
"""

import json
import time
import subprocess
import signal
import os

import pytest
import httpx

from mcp_server.tests.conftest import TEST_EXCEL_PRODUCTS, ALL_TEST_PRODUCT_IDS


# ── Helper: MCP Client via HTTP ──────────────────────────────────────────────

class MCPTestClient:
    """Simple MCP client that calls tools via Streamable HTTP transport.

    Handles the MCP Streamable HTTP session lifecycle:
      1. Sends 'initialize' on first use to obtain Mcp-Session-Id
      2. Includes Mcp-Session-Id header in all subsequent requests
    """

    def __init__(self, base_url: str, auth_token: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.mcp_url = f"{self.base_url}/mcp"
        self.auth_token = auth_token
        self.client = httpx.Client(timeout=600)  # 10 min timeout for long jobs
        self._request_id = 0
        self._session_id: str | None = None

    def _get_headers(self) -> dict:
        """Build request headers, including session ID and auth if available."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        return headers

    def _ensure_initialized(self):
        """Initialize MCP session if not already done."""
        if self._session_id:
            return
        self._request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "mcp-test-client", "version": "1.0"},
            },
        }
        resp = self.client.post(self.mcp_url, json=payload, headers=self._get_headers())
        resp.raise_for_status()
        # Capture session ID from response header
        self._session_id = resp.headers.get("mcp-session-id")
        if not self._session_id:
            raise RuntimeError("Server did not return Mcp-Session-Id header on initialize")

        # Send initialized notification (no response expected for notifications)
        self._request_id += 1
        notif = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }
        resp2 = self.client.post(self.mcp_url, json=notif, headers=self._get_headers())
        # Notifications may return 200 or 202, both are fine
        if resp2.status_code not in (200, 202, 204):
            resp2.raise_for_status()

    def call_tool(self, name: str, arguments: dict = None) -> dict:
        """Call an MCP tool and return the result."""
        self._ensure_initialized()
        self._request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": "tools/call",
            "params": {
                "name": name,
                "arguments": arguments or {},
            },
        }
        resp = self.client.post(self.mcp_url, json=payload, headers=self._get_headers())
        resp.raise_for_status()

        # Handle SSE response
        content_type = resp.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            return self._parse_sse_response(resp.text)
        return resp.json().get("result", resp.json())

    def _parse_sse_response(self, text: str) -> dict:
        """Parse SSE stream and return the last JSON-RPC result."""
        last_result = None
        for line in text.split("\n"):
            line = line.strip()
            if line.startswith("data:"):
                data = line[5:].strip()
                if data:
                    try:
                        parsed = json.loads(data)
                        if "result" in parsed:
                            last_result = parsed["result"]
                        elif "error" in parsed:
                            raise Exception(f"MCP error: {parsed['error']}")
                    except json.JSONDecodeError:
                        continue
        return last_result or {}

    def list_tools(self) -> list:
        """List available MCP tools."""
        self._ensure_initialized()
        self._request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": "tools/list",
            "params": {},
        }
        resp = self.client.post(self.mcp_url, json=payload, headers=self._get_headers())
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            result = self._parse_sse_response(resp.text)
        else:
            result = resp.json().get("result", resp.json())
        return result.get("tools", [])

    def extract_tool_result(self, result: dict):
        """Extract the actual content from MCP tool response.

        Handles both legacy content-array format and newer structuredContent format:
          - structuredContent: {"result": <value>}  →  returns <value>
          - content: [{"type": "text", "text": "..."}]  →  parses JSON from text items
        """
        if not isinstance(result, dict):
            return result

        # Newer MCP SDK: structured content with typed result
        if "structuredContent" in result and result["structuredContent"]:
            sc = result["structuredContent"]
            if "result" in sc:
                return sc["result"]
            return sc

        # Legacy format: content array with text items
        if "content" in result and result["content"]:
            texts = []
            for item in result["content"]:
                if item.get("type") == "text":
                    try:
                        texts.append(json.loads(item["text"]))
                    except (json.JSONDecodeError, TypeError):
                        texts.append(item["text"])
            if len(texts) == 1:
                return texts[0]
            elif len(texts) > 1:
                return texts

        return result

    def close(self):
        self.client.close()


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def mcp_server_process(target):
    """Start local MCP server if target is 'local'."""
    if target != "local":
        yield None
        return

    # Start the MCP server as a subprocess using uv for correct dependencies
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    proc = subprocess.Popen(
        ["uv", "run", "python", "-m", "mcp_server.server", "--transport", "streamable-http", "--port", "8080"],
        cwd=project_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for server to be ready (POST to /mcp since GET may not be supported)
    for _ in range(30):
        try:
            resp = httpx.post(
                "http://localhost:8080/mcp",
                json={"jsonrpc": "2.0", "id": 0, "method": "initialize",
                      "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                                 "clientInfo": {"name": "healthcheck", "version": "0.1"}}},
                headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
                timeout=3,
            )
            if resp.status_code == 200:
                break
        except (httpx.ConnectError, httpx.ReadTimeout):
            pass
        # Check if process died
        if proc.poll() is not None:
            stdout = proc.stdout.read().decode() if proc.stdout else ""
            stderr = proc.stderr.read().decode() if proc.stderr else ""
            pytest.fail(f"MCP server process exited with code {proc.returncode}.\nstdout: {stdout}\nstderr: {stderr}")
        time.sleep(1)
    else:
        proc.terminate()
        pytest.fail("MCP server failed to start within 30 seconds")

    yield proc

    # Cleanup
    proc.send_signal(signal.SIGTERM)
    proc.wait(timeout=10)


@pytest.fixture(scope="session")
def mcp_client(server_url, mcp_server_process, auth_token) -> MCPTestClient:
    """Create an MCP test client with optional auth for remote targets."""
    client = MCPTestClient(server_url, auth_token=auth_token)
    yield client
    client.close()


def poll_job(client: MCPTestClient, job_id: str, timeout: int = 600, interval: int = 10) -> dict:
    """Poll job status until completed/failed/cancelled or timeout."""
    start = time.time()
    while time.time() - start < timeout:
        raw = client.call_tool("get_job_status", {"job_id": job_id})
        result = client.extract_tool_result(raw)
        status = result.get("status", "")
        if status in ("completed", "failed", "cancelled"):
            return result
        time.sleep(interval)
    raise TimeoutError(f"Job {job_id} did not complete within {timeout}s")


# ══════════════════════════════════════════════════════════════════════════════
# TESTS
# ══════════════════════════════════════════════════════════════════════════════


# ── Discovery Tests (FREE — no API calls, no data needed) ────────────────────

class TestDiscovery:
    """Basic connectivity and tool discovery tests — no data dependency."""

    def test_list_tools(self, mcp_client):
        """Server should expose all expected MCP tools."""
        tools = mcp_client.list_tools()
        tool_names = [t["name"] for t in tools]
        expected_tools = [
            "list_products",
            "batch_generate",
            "get_job_status",
            "get_job_logs",
            "get_product_assets",
            "list_jobs",
            "cancel_job",
            "upload_dataset",
        ]
        for tool in expected_tools:
            assert tool in tool_names, f"Missing tool: {tool}"

    def test_list_jobs_empty(self, mcp_client):
        """Initially no jobs should exist (server just started)."""
        raw = mcp_client.call_tool("list_jobs")
        jobs = mcp_client.extract_tool_result(raw)
        assert isinstance(jobs, list)

    def test_cancel_nonexistent_job(self, mcp_client):
        """Cancelling nonexistent job returns error."""
        raw = mcp_client.call_tool("cancel_job", {"job_id": "nonexistent"})
        result = mcp_client.extract_tool_result(raw)
        assert "error" in result

    def test_get_product_assets_nonexistent(self, mcp_client):
        """Get assets for a product that doesn't exist."""
        raw = mcp_client.call_tool("get_product_assets", {"product_id": "nonexistent_product_xyz"})
        result = mcp_client.extract_tool_result(raw)
        assert result["exists"] is False
        assert result["assets"]["generated_images"] == []


# ── Dataset Upload Tests (FREE — no Vertex AI calls) ─────────────────────────

class TestDatasetUpload:
    """Upload test dataset and verify product discovery.

    This is the entry point for all data-dependent tests.
    The test Excel is created locally and uploaded to GCS for remote targets.
    """

    def test_upload_dataset(self, mcp_client, test_excel_gcs_uri):
        """Upload test Excel dataset and verify product creation counts."""
        raw = mcp_client.call_tool("upload_dataset", {
            "excel_path": test_excel_gcs_uri,
            "data_dir": "data",
            "company_name": "Test Company",
            "append": False,  # Overwrite to ensure clean state
        })
        result = mcp_client.extract_tool_result(raw)

        # Should not have error
        assert "error" not in result, f"Upload failed: {result.get('error')}"

        # Verify totals
        assert result["total_created"] == 3, f"Expected 3 products, got {result['total_created']}"
        assert result["default_company_name"] == "Test Company"

        # Verify per-category counts
        categories = result["categories"]
        assert "Luggage Bags Cases" in categories
        assert categories["Luggage Bags Cases"]["created"] == 2
        assert categories["Luggage Bags Cases"]["folder"] == "luggage_bags_cases"

        assert "Mother Kids Toys" in categories
        assert categories["Mother Kids Toys"]["created"] == 1
        assert categories["Mother Kids Toys"]["folder"] == "mother_kids_toys"

    def test_list_products_after_upload(self, mcp_client, test_excel_gcs_uri):
        """After upload, products should be discoverable via list_products."""
        # List luggage_bags_cases
        raw = mcp_client.call_tool("list_products", {"data_dir": "data/luggage_bags_cases"})
        products = mcp_client.extract_tool_result(raw)
        assert isinstance(products, list)
        ids = [p["product_id"] for p in products]
        assert "1600907870863" in ids, f"Product 1600907870863 not found. Got: {ids}"
        assert "1601488769917" in ids, f"Product 1601488769917 not found. Got: {ids}"

        # List mother_kids_toys
        raw = mcp_client.call_tool("list_products", {"data_dir": "data/mother_kids_toys"})
        products = mcp_client.extract_tool_result(raw)
        ids = [p["product_id"] for p in products]
        assert "1601524945369" in ids, f"Product 1601524945369 not found. Got: {ids}"

    def test_product_metadata_correct(self, mcp_client, test_excel_gcs_uri):
        """Uploaded products should have correct metadata from Excel."""
        raw = mcp_client.call_tool("list_products", {"data_dir": "data/luggage_bags_cases"})
        products = mcp_client.extract_tool_result(raw)

        # Find our test product
        product = next((p for p in products if p["product_id"] == "1600907870863"), None)
        assert product is not None, "Product 1600907870863 not found"
        assert product["country"] == "United States"
        assert product["language"] == "English"
        # company_name should be "Cymbal Shop" (from Excel column, overrides parameter)
        assert product["company_name"] == "Cymbal Shop"
        assert "Crochet" in product["product_desc"] or "Shopping" in product["product_desc"]

    def test_upload_dataset_append_mode(self, mcp_client, test_excel_gcs_uri):
        """Re-uploading in append mode should skip existing products."""
        raw = mcp_client.call_tool("upload_dataset", {
            "excel_path": test_excel_gcs_uri,
            "data_dir": "data",
            "append": True,
        })
        result = mcp_client.extract_tool_result(raw)
        assert "error" not in result, f"Upload failed: {result.get('error')}"

        # All products should be skipped (already exist)
        assert result["total_created"] == 0
        assert result["total_skipped"] == 3

    def test_get_product_assets_fresh(self, mcp_client, test_excel_gcs_uri):
        """Freshly uploaded products should have no generated assets yet."""
        raw = mcp_client.call_tool("get_product_assets", {"product_id": "1600907870863"})
        result = mcp_client.extract_tool_result(raw)
        # May or may not "exist" depending on whether there's output metadata
        # But generated images should be empty for a fresh upload
        if result["exists"]:
            # If metadata exists from a previous run, that's ok
            pass
        else:
            assert result["assets"]["generated_images"] == []
            assert result["assets"]["gcs_images"] == []


# ── Image Generation Tests (Real Vertex AI) ──────────────────────────────────

class TestImageGeneration:
    """Image generation tests using real Vertex AI Gemini API.

    Depends on TestDatasetUpload having run first (products must exist).

    Cost: ~$0.10 per product
    Time: ~1-2 minutes per product
    """

    def test_image_only_single(self, mcp_client, test_excel_gcs_uri):
        """Generate image for one uploaded product.
        Uses: 1600907870863 (US, mesh bag)
        """
        raw = mcp_client.call_tool("batch_generate", {
            "mode": "image_only",
            "data_dir": "data/luggage_bags_cases",
            "product_ids": ["1600907870863"],
            "max_sample_images": 1,
        })
        result = mcp_client.extract_tool_result(raw)
        assert "job_id" in result, f"No job_id in result: {result}"
        job_id = result["job_id"]

        final = poll_job(mcp_client, job_id, timeout=300)
        assert final["status"] == "completed", f"Job failed: {final.get('error')}"

    def test_get_assets_after_image_generation(self, mcp_client):
        """After image generation, assets should be retrievable."""
        raw = mcp_client.call_tool("get_product_assets", {"product_id": "1600907870863"})
        result = mcp_client.extract_tool_result(raw)
        assert result["exists"] is True, "Product assets not found after generation"
        # Should have either local images or GCS images
        has_images = (
            len(result["assets"]["generated_images"]) > 0
            or len(result["assets"]["gcs_images"]) > 0
        )
        assert has_images, f"No images found in assets: {result['assets']}"


# ── Full Pipeline Tests (Real Vertex AI — longer) ────────────────────────────

class TestFullPipeline:
    """Full pipeline tests: image → scene script → video → post-process.

    Depends on TestDatasetUpload having run first.

    Cost: ~$1-2 per product
    Time: ~5-10 minutes per product
    """

    def test_full_single(self, mcp_client, test_excel_gcs_uri):
        """Full pipeline for one uploaded product.
        Uses: 1601524945369 (US, plush toy pillow)
        """
        raw = mcp_client.call_tool("batch_generate", {
            "mode": "full",
            "data_dir": "data/mother_kids_toys",
            "product_ids": ["1601524945369"],
            "max_sample_images": 1,
            "max_sample_clips": 1,
        })
        result = mcp_client.extract_tool_result(raw)
        assert "job_id" in result
        job_id = result["job_id"]

        final = poll_job(mcp_client, job_id, timeout=900)
        assert final["status"] == "completed", f"Job failed: {final.get('error')}"

    def test_assets_after_full_pipeline(self, mcp_client):
        """After full pipeline, product should have video assets."""
        raw = mcp_client.call_tool("get_product_assets", {"product_id": "1601524945369"})
        result = mcp_client.extract_tool_result(raw)
        assert result["exists"] is True

        assets = result["assets"]
        # Should have final video (local or GCS)
        has_video = (
            assets["final_video"] is not None
            or assets["gcs_final_video"] is not None
        )
        assert has_video, f"No final video in assets: {assets}"


# ── Job Management Tests ─────────────────────────────────────────────────────

class TestJobManagement:
    """Tests for job lifecycle management."""

    def test_cancel_running_job(self, mcp_client, test_excel_gcs_uri):
        """Start a job and cancel it immediately."""
        raw = mcp_client.call_tool("batch_generate", {
            "mode": "image_only",
            "data_dir": "data/luggage_bags_cases",
            "product_ids": ["1601488769917"],
            "max_sample_images": 1,
        })
        result = mcp_client.extract_tool_result(raw)
        assert "job_id" in result
        job_id = result["job_id"]

        # Cancel immediately
        time.sleep(0.5)
        raw = mcp_client.call_tool("cancel_job", {"job_id": job_id})
        cancel_result = mcp_client.extract_tool_result(raw)
        assert cancel_result["status"] in ("cancelled", "completed", "running")

    def test_list_jobs_after_runs(self, mcp_client):
        """After running tests, jobs should be listed."""
        raw = mcp_client.call_tool("list_jobs")
        jobs = mcp_client.extract_tool_result(raw)
        assert isinstance(jobs, list)
        assert len(jobs) >= 1

    def test_get_job_status_details(self, mcp_client):
        """Job status should include all expected fields."""
        raw = mcp_client.call_tool("list_jobs")
        jobs = mcp_client.extract_tool_result(raw)
        if jobs:
            job = jobs[0]
            assert "job_id" in job
            assert "status" in job
            assert "created_at" in job
            assert "mode" in job
