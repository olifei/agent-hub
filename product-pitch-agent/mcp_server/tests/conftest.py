"""
Test configuration for MCP Server E2E tests.

Supports testing against both local and remote (deployed) servers:
  pytest --target=local          # Start local server subprocess
  pytest --target=http://...     # Test against deployed Cloud Run URL

For remote targets, auth is handled via SA impersonation:
  gcloud auth print-identity-token --impersonate-service-account=...
"""

import os
import subprocess
import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--target",
        default="local",
        help="Target server: 'local' (start subprocess) or URL like 'https://mcp-server-xxx.run.app'",
    )
    parser.addoption(
        "--sa",
        default=None,
        help="Service account email for SA impersonation (remote targets). "
             "If not set, auto-detects from project number in the URL.",
    )
    parser.addoption(
        "--gcs-bucket",
        default=None,
        help="GCS bucket for uploading test Excel (remote targets). "
             "Auto-detects from GCS_BUCKET_NAME env var or defaults to project bucket.",
    )
    parser.addoption(
        "--token",
        default=None,
        help="Pre-generated Bearer token (skips slow SA impersonation, lasts 1 hour). "
             "Generate with: gcloud auth print-identity-token --audiences=URL "
             "--impersonate-service-account=SA --include-email",
    )


@pytest.fixture(scope="session")
def target(request):
    return request.config.getoption("--target")


@pytest.fixture(scope="session")
def server_url(target):
    """Return the MCP server URL for HTTP-based tests."""
    if target == "local":
        return "http://localhost:8080"
    return target


@pytest.fixture(scope="session")
def auth_token(target, server_url, request):
    """Get a bearer token for remote Cloud Run targets.

    Uses service account impersonation to get an identity token
    with the service URL as the audience.
    Returns None for local targets.

    Pass --token=<TOKEN> to skip the slow SA impersonation step.
    Tokens last 1 hour.
    """
    if target == "local":
        return None

    # Use pre-generated token if provided (skips slow SA impersonation)
    pre_token = request.config.getoption("--token")
    if pre_token:
        return pre_token

    sa_email = request.config.getoption("--sa")
    if not sa_email:
        # Auto-detect: extract project number from URL like
        # https://ads-video-mcp-server-72273101339.us-central1.run.app
        import re
        m = re.search(r"-(\d{10,})\.", server_url)
        if m:
            project_number = m.group(1)
            sa_email = f"{project_number}-compute@developer.gserviceaccount.com"
        else:
            pytest.skip("Cannot determine SA email. Use --sa=EMAIL or ensure URL contains project number.")

    try:
        result = subprocess.run(
            [
                "gcloud", "auth", "print-identity-token",
                f"--audiences={server_url}",
                f"--impersonate-service-account={sa_email}",
                "--include-email",
            ],
            capture_output=True, text=True, timeout=30,
        )
        token = result.stdout.strip()
        if not token or token.startswith("ERROR") or token.startswith("WARNING"):
            pytest.fail(f"Failed to get identity token: {result.stderr}")
        return token
    except Exception as e:
        pytest.fail(f"Failed to get identity token: {e}")


@pytest.fixture(scope="session")
def gcs_bucket(request):
    """GCS bucket for uploading test data."""
    bucket = request.config.getoption("--gcs-bucket")
    if bucket:
        return bucket
    return os.environ.get("GCS_BUCKET_NAME", "jingyiwa-product-pitch-flow")


@pytest.fixture(scope="session")
def test_excel_gcs_uri(target, gcs_bucket):
    """Create a test Excel file and upload to GCS for remote testing.

    Returns the GCS URI (gs://bucket/path) for remote targets,
    or the local path for local targets.
    """
    from mcp_server.tests.create_test_excel import create_test_dataset

    local_path = "mcp_server/tests/test_dataset.xlsx"
    create_test_dataset(local_path)

    if target == "local":
        # For local targets, use the local file path
        return os.path.abspath(local_path)

    # For remote targets, upload to GCS
    gcs_key = "_test_uploads/test_dataset.xlsx"
    gcs_uri = f"gs://{gcs_bucket}/{gcs_key}"

    result = subprocess.run(
        ["gsutil", "cp", local_path, gcs_uri],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        pytest.fail(f"Failed to upload test Excel to GCS: {result.stderr}")

    yield gcs_uri

    # Cleanup: remove from GCS after tests
    subprocess.run(
        ["gsutil", "rm", gcs_uri],
        capture_output=True, text=True, timeout=30,
    )


# ── Test products from the test Excel ────────────────────────────────────────

# These match what create_test_excel.py generates
TEST_EXCEL_PRODUCTS = {
    "luggage_bags_cases": {
        "product_ids": ["1600907870863", "1601488769917"],
        "data_dir": "data/luggage_bags_cases",
        "expected_count": 2,
    },
    "mother_kids_toys": {
        "product_ids": ["1601524945369"],
        "data_dir": "data/mother_kids_toys",
        "expected_count": 1,
    },
}

# All test product IDs from the Excel (flat list)
ALL_TEST_PRODUCT_IDS = ["1600907870863", "1601488769917", "1601524945369"]


# Legacy test products (for tests using pre-existing data/ directory)
TEST_PRODUCTS = {
    "luggage_bags_cases": {
        "product_id": "1601442859214",
        "data_dir": "data/luggage_bags_cases",
        "expected_country": "United States",
        "expected_language": "English",
    },
    "mother_kids_toys": {
        "product_id": "1600242921466",
        "data_dir": "data/mother_kids_toys",
        "expected_country": "United States",
        "expected_language": "English",
    },
    "makeup": {
        "product_id": "1601296191928",
        "data_dir": "data/makeup",
        "expected_country": "United States",
        "expected_language": "English",
    },
    "accessories": {
        "product_id": "accessories_01",
        "data_dir": "data",
        "expected_country": "Japan",
        "expected_language": "Japanese",
    },
    "bags": {
        "product_id": "bags_01",
        "data_dir": "data",
        "expected_country": None,
        "expected_language": None,
    },
}


@pytest.fixture(scope="session")
def test_products():
    return TEST_PRODUCTS
