"""
MCP Server for Ads Video Generation Pipeline.

Exposes pipeline capabilities as MCP tools and resources
via Streamable HTTP transport for Cloud Run deployment.

Auth: IAP (Identity-Aware Proxy) provides authentication.
      User identity extracted from X-Goog-Authenticated-User-Email header.

Execution modes:
  - LOCAL: Pipeline runs in background threads (for development)
  - CLOUD_RUN_JOBS: Pipeline dispatched as Cloud Run Jobs (for production)

Set EXECUTION_MODE=cloud_run_jobs to enable Cloud Run Jobs dispatch.
"""

import os
import json
import logging
import threading

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from mcp_server.job_manager import job_manager, JobStatus
from mcp_server.pipeline.orchestrator import (
    get_all_product_directories,
    process_product,
    process_product_image_only,
    batch_process,
    batch_process_image_only,
)
from mcp_server.pipeline.metadata import (
    load_product_metadata,
    load_existing_metadata,
)
from mcp_server.pipeline.config import settings
from mcp_server.pipeline.user_context import set_user_id, get_output_base_dir, get_gcs_prefix
from mcp_server.pipeline.gcs_service import gcs_service

logger = logging.getLogger(__name__)

# Execution mode: "local" (threads) or "cloud_run_jobs" (Cloud Run Jobs API)
EXECUTION_MODE = os.environ.get("EXECUTION_MODE", "local")

# ── Create MCP Server ────────────────────────────────────────────────────────

mcp = FastMCP(
    "ads-video-pipeline",
    instructions=(
        "MCP server for Ads Video Generation Pipeline. "
        "Generate product advertisement images and videos using Vertex AI (Gemini + Veo). "
        "Use list_products to discover products, batch_generate to start generation jobs, "
        "get_job_status to track progress, and get_product_assets to retrieve results."
    ),
    host="0.0.0.0",
    port=int(os.environ.get("PORT", "8080")),
    # Disable DNS rebinding protection for Cloud Run deployment.
    # Cloud Run handles auth via IAM; the Host header will be the external URL.
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
    ),
    stateless_http=True,
    json_response=True,
)


# ── IAP User Identity ────────────────────────────────────────────────────────

def _get_user_id() -> str:
    """Extract user identity from IAP headers.

    IAP sets these headers after authenticating the user:
    - X-Goog-Authenticated-User-Email: accounts.google.com:user@example.com
    - X-Goog-Authenticated-User-Id: accounts.google.com:1234567890

    Falls back to 'anonymous' for local development (no IAP).
    """
    # In production, IAP headers are available in the ASGI/WSGI scope
    # For FastMCP, we check environment or use a default
    email = os.environ.get("IAP_USER_EMAIL", "anonymous")
    if email.startswith("accounts.google.com:"):
        email = email.split(":", 1)[1]
    return email


# ── MCP Tools ─────────────────────────────────────────────────────────────────

@mcp.tool()
def list_products(data_dir: str = "data") -> list[dict]:
    """List all available products from the data directory.

    Discovers product folders containing metadata.json files.
    Tries local filesystem first, then falls back to GCS data store.

    Args:
        data_dir: Root data directory to scan (default: "data")

    Returns:
        List of product info dicts with product_id, path, and metadata.
    """
    user_id = _get_user_id()
    set_user_id(user_id)

    product_dirs = get_all_product_directories(data_dir)
    products = []
    for pd in product_dirs:
        try:
            metadata = load_product_metadata(pd)
            product_id = os.path.basename(pd)
            products.append({
                "product_id": product_id,
                "path": pd,
                "country": metadata.get("country", ""),
                "language": metadata.get("language", "English"),
                "product_desc": metadata.get("product_desc", ""),
                "company_name": metadata.get("company_name", ""),
            })
        except Exception as e:
            logger.warning(f"Failed to load metadata for {pd}: {e}")
    return products


@mcp.tool()
def get_product_assets(product_id: str, output_dir: str = None) -> dict:
    """Get generated assets (images, videos, metadata) for a product.

    Returns GCS URIs for generated assets. In cloud mode, metadata is
    stored in GCS alongside the generated files.
    Tries local filesystem first, then falls back to GCS.

    Args:
        product_id: The product identifier (folder name)
        output_dir: Base output directory (default: user-scoped output dir)

    Returns:
        Dict with product status, generated images, videos, GCS URIs, and metadata.
    """
    user_id = _get_user_id()
    set_user_id(user_id)

    if output_dir is None:
        output_dir = get_output_base_dir()

    product_output = os.path.join(output_dir, product_id)
    result = {
        "product_id": product_id,
        "output_dir": product_output,
        "exists": False,
        "assets": {
            "generated_images": [],
            "generated_videos": [],
            "final_video": None,
            "metadata": None,
            "gcs_images": [],
            "gcs_videos": [],
            "gcs_final_video": None,
        },
    }

    # load_existing_metadata already has local → GCS fallback
    metadata = load_existing_metadata(product_output)
    if not metadata:
        return result

    result["exists"] = True
    result["assets"]["metadata"] = metadata

    # Extract GCS URIs from metadata (preferred in cloud mode)
    starting_frames = metadata.get("starting_frames") or {}
    if starting_frames:
        # GCS URIs from results field (image generation stores full gs:// URIs here)
        for uri in starting_frames.get("results", []):
            if isinstance(uri, str) and uri.startswith("gs://"):
                result["assets"]["gcs_images"].append(uri)
        for path in starting_frames.get("local_paths", []):
            if os.path.exists(path):
                result["assets"]["generated_images"].append(path)

    video_clips = metadata.get("video_clips") or {}
    if video_clips:
        for uri in video_clips.get("veo_results", []):
            if isinstance(uri, str) and uri.startswith("gs://"):
                result["assets"]["gcs_videos"].append(uri)
        for path in video_clips.get("veo_local_path", []):
            if os.path.exists(path):
                result["assets"]["generated_videos"].append(path)

    final_video = metadata.get("final_video") or {}
    if final_video:
        gcs_uri = final_video.get("result") or final_video.get("gcs_uri")
        if gcs_uri and isinstance(gcs_uri, str) and gcs_uri.startswith("gs://"):
            result["assets"]["gcs_final_video"] = gcs_uri
        if final_video.get("local_path") and os.path.exists(final_video["local_path"]):
            result["assets"]["final_video"] = final_video["local_path"]

    return result


@mcp.tool()
def batch_generate(
    mode: str = "full",
    data_dir: str = "data",
    product_ids: list[str] = None,
    company_name: str = None,
    max_sample_images: int = None,
    max_sample_clips: int = None,
    max_workers: int = 1,
    force: bool = False,
    aspect_ratio: str = "16:9",
) -> dict:
    """Start a batch generation job for product ad images and/or videos.

    Runs asynchronously — returns a job_id to track progress.
    In production, dispatches work as a Cloud Run Job.
    In local mode, runs in a background thread.

    Args:
        mode: Pipeline mode - "full" (image+video+postprocess) or "image_only"
        data_dir: Root data directory containing product folders
        product_ids: Optional list of specific product IDs to process
        company_name: Company name for branding. If None, reads from each product's
            metadata.json "company_name" field, falling back to "Cymbal Shop".
        max_sample_images: Max image generation attempts per product. If None,
            uses settings.MAX_SAMPLE_IMAGES (default 1).
        max_sample_clips: Max video generation attempts per product. If None,
            uses settings.MAX_SAMPLE_CLIPS (default 1).
        max_workers: Number of parallel workers (default: 1)
        force: Re-process even if already completed (default: False)
        aspect_ratio: Target aspect ratio - "16:9" or "9:16" (default: "16:9")

    Returns:
        Dict with job_id and status for tracking.
    """
    user_id = _get_user_id()
    params = {
        "mode": mode,
        "data_dir": data_dir,
        "product_ids": product_ids,
        "company_name": company_name,
        "max_sample_images": max_sample_images,
        "max_sample_clips": max_sample_clips,
        "max_workers": max_workers,
        "force": force,
        "aspect_ratio": aspect_ratio,
    }

    if EXECUTION_MODE == "cloud_run_jobs":
        # Cloud Run is the source of truth: dispatch synchronously, use the
        # execution suffix Cloud Run assigns as the agent-facing job_id.
        from mcp_server.cloud_run_jobs import submit_pipeline_job

        exec_info = submit_pipeline_job(
            mode=mode,
            data_dir=data_dir,
            product_ids=product_ids,
            company_name=company_name,
            max_sample_images=max_sample_images,
            max_sample_clips=max_sample_clips,
            force=force,
            aspect_ratio=aspect_ratio,
            user_id=user_id,
        )
        job_id = exec_info.get("job_id", "")
        return {
            "job_id": job_id,
            "user_id": user_id,
            "status": "running",
            "execution_mode": EXECUTION_MODE,
            "message": f"Job started. Use get_job_status(job_id='{job_id}') to track progress.",
        }

    # Local mode: thread + in-memory JobManager (dev convenience).
    job = job_manager.create_job(mode=mode, params=params, user_id=user_id)
    params["user_id"] = user_id
    thread = threading.Thread(
        target=_run_pipeline_local,
        args=(job.job_id, params),
        daemon=True,
    )
    thread.start()
    return {
        "job_id": job.job_id,
        "user_id": user_id,
        "status": job.status.value,
        "execution_mode": EXECUTION_MODE,
        "message": f"Job started. Use get_job_status(job_id='{job.job_id}') to track progress.",
    }


@mcp.tool()
def get_job_status(job_id: str, include_logs: bool = False, max_log_entries: int = 20) -> dict:
    """Get the current status of a pipeline job.

    For Cloud Run Jobs, also fetches execution status and optionally
    recent log entries showing pipeline progress (e.g. which step is running).

    Args:
        job_id: The job identifier returned by batch_generate.
        include_logs: If True, include recent Cloud Logging entries (default: False).
        max_log_entries: Max log entries to include when include_logs=True (default: 20).

    Returns:
        Dict with job status, progress, results if completed, and optionally logs.
    """
    user_id = _get_user_id()

    if EXECUTION_MODE == "cloud_run_jobs":
        from mcp_server.cloud_run_jobs import (
            execution_name_from_job_id,
            get_execution_status,
            get_execution_logs,
            get_execution_pipeline_params,
            read_job_result,
        )

        execution_name = execution_name_from_job_id(job_id)
        exec_status = get_execution_status(execution_name)
        if exec_status.get("status") == "unknown" and exec_status.get("error"):
            return {"error": f"Job '{job_id}' not found: {exec_status['error']}"}

        params = get_execution_pipeline_params(execution_name)
        set_user_id(user_id)
        gcs_result = read_job_result(
            job_id, get_gcs_prefix(), os.environ.get("GCS_BUCKET_NAME", "")
        )

        result = {
            "job_id": job_id,
            "user_id": user_id,
            "mode": params.get("mode"),
            "params": params,
            "status": exec_status.get("status"),
            "created_at": exec_status.get("start_time"),
            "updated_at": exec_status.get("completion_time") or exec_status.get("start_time"),
            "error": exec_status.get("error") or (gcs_result or {}).get("error"),
            "result": (gcs_result or {}).get("results"),
            "cloud_run_execution": exec_status,
        }
        if include_logs:
            result["recent_logs"] = get_execution_logs(
                execution_name, max_entries=max_log_entries, severity_min="DEFAULT"
            )
        return result

    # Local mode
    job = job_manager.get_job(job_id, user_id=user_id)
    if not job:
        return {"error": f"Job '{job_id}' not found"}
    return job.to_dict()


@mcp.tool()
def get_job_logs(job_id: str, max_entries: int = 100, severity: str = "DEFAULT") -> dict:
    """Get detailed logs for a pipeline job.

    Fetches Cloud Logging entries for the Cloud Run Job execution,
    showing pipeline progress, Vertex AI calls, evaluation results, etc.

    Args:
        job_id: The job identifier returned by batch_generate.
        max_entries: Maximum number of log entries to return (default: 100).
        severity: Minimum severity filter — "DEFAULT", "INFO", "WARNING", "ERROR" (default: "DEFAULT").

    Returns:
        Dict with job info and log entries.
    """
    user_id = _get_user_id()

    if EXECUTION_MODE == "cloud_run_jobs":
        from mcp_server.cloud_run_jobs import (
            execution_name_from_job_id,
            get_execution_status,
            get_execution_logs,
        )
        execution_name = execution_name_from_job_id(job_id)
        exec_status = get_execution_status(execution_name)
        if exec_status.get("status") == "unknown" and exec_status.get("error"):
            return {"error": f"Job '{job_id}' not found: {exec_status['error']}"}
        return {
            "job_id": job_id,
            "status": exec_status.get("status"),
            "logs": get_execution_logs(
                execution_name, max_entries=max_entries, severity_min=severity
            ),
        }

    # Local mode
    job = job_manager.get_job(job_id, user_id=user_id)
    if not job:
        return {"error": f"Job '{job_id}' not found"}
    return {
        "job_id": job_id,
        "status": job.status.value,
        "mode": job.mode,
        "logs": [{"message": "Logs only available for Cloud Run Jobs execution mode"}],
    }


@mcp.tool()
def list_jobs(max_results: int = 50) -> list[dict]:
    """List recent pipeline jobs for the current user.

    In cloud_run_jobs mode, lists Cloud Run Job executions (filtered by USER_ID
    env var on each execution when a non-anonymous user is set).
    """
    user_id = _get_user_id()

    if EXECUTION_MODE == "cloud_run_jobs":
        from mcp_server.cloud_run_jobs import list_executions
        jobs = list_executions(max_results=max_results)
        if user_id and user_id != "anonymous":
            jobs = [j for j in jobs if j.get("user_id") == user_id]
        return jobs

    return job_manager.list_jobs(user_id=user_id)


@mcp.tool()
def cancel_job(job_id: str) -> dict:
    """Cancel a running pipeline job."""
    user_id = _get_user_id()

    if EXECUTION_MODE == "cloud_run_jobs":
        from mcp_server.cloud_run_jobs import (
            execution_name_from_job_id,
            cancel_execution,
        )
        execution_name = execution_name_from_job_id(job_id)
        return cancel_execution(execution_name)

    result = job_manager.cancel_job(job_id, user_id=user_id)
    if not result:
        return {"error": f"Job '{job_id}' not found"}
    return result


@mcp.tool()
def upload_dataset(
    excel_path: str,
    data_dir: str = "data",
    company_name: str = None,
    sample_counts: int = None,
    append: bool = True,
) -> dict:
    """Upload a product dataset from an Excel file to create product folders.

    Reads the Excel file where each sheet is a product category.
    Creates product subfolders with metadata.json and downloads product images.

    Expected Excel columns:
      - product_id  — required (unique product identifier)
      - product_name  — required (product description for ad copy)
      - country  — target country (full name or code e.g. "US", "United States")
      - language  — speech language (full name or code e.g. "en", "English")
      - image_url  — product image URL to download
      - company_name  — company/brand name per product (e.g. "Cymbal Shop")

    Each sheet in the Excel becomes a product category subfolder.
    If the "company_name" column exists, each product gets its own
    company_name in metadata.json. Otherwise the company_name parameter
    is used as a blanket default for all products.

    Args:
        excel_path: Path to the Excel file on the server filesystem
        data_dir: Base data directory for product folders (default: "data")
        company_name: Fallback company name when the Excel has no "company_name"
            column (or a row's value is empty). Defaults to "Cymbal Shop".
        sample_counts: Max products to sample per category. None = all.
        append: If True, skip existing products. If False, overwrite.

    Returns:
        Dict with created product counts per category and total.
    """
    import re
    from pathlib import Path

    try:
        import openpyxl  # noqa: F401 — ensure available
        import pandas as pd  # noqa: F401
    except ImportError:
        return {"error": "openpyxl and pandas are required. Install with: pip install openpyxl pandas"}

    if company_name is None:
        company_name = settings.DEFAULT_COMPANY_NAME

    # Support GCS URIs: download to temp file first
    _temp_excel = None
    if excel_path.startswith("gs://"):
        import tempfile
        try:
            # Parse gs://bucket/key
            parts = excel_path[5:].split("/", 1)
            if len(parts) != 2:
                return {"error": f"Invalid GCS URI: {excel_path}"}
            bucket_name, blob_key = parts
            from google.cloud import storage as gcs_storage
            client = gcs_storage.Client()
            bucket = client.bucket(bucket_name)
            blob = bucket.blob(blob_key)
            if not blob.exists():
                return {"error": f"GCS file not found: {excel_path}"}
            _temp_excel = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
            blob.download_to_filename(_temp_excel.name)
            _temp_excel.close()
            excel_path = _temp_excel.name
            logger.info(f"Downloaded Excel from GCS to {excel_path}")
        except Exception as e:
            if _temp_excel and os.path.exists(_temp_excel.name):
                os.unlink(_temp_excel.name)
            return {"error": f"Failed to download from GCS: {e}"}

    if not os.path.exists(excel_path):
        return {"error": f"Excel file not found: {excel_path}"}

    # Country/language code mappings
    country_map = {
        "US": "United States", "UK": "United Kingdom", "GB": "United Kingdom",
        "DE": "Germany", "FR": "France", "ES": "Spain", "IT": "Italy",
        "JP": "Japan", "CN": "China", "AU": "Australia", "CA": "Canada",
    }
    language_map = {
        "en": "English", "zh": "Chinese", "de": "German", "fr": "French",
        "es": "Spanish", "it": "Italian", "ja": "Japanese", "pt": "Portuguese",
    }

    def sanitize_folder_name(name: str) -> str:
        sanitized = re.sub(r"[,\s&]+", "_", name.lower())
        sanitized = re.sub(r"_+", "_", sanitized).strip("_")
        return sanitized

    def download_image(url: str, save_dir: Path) -> bool:
        """Download a product image from either a gs:// URI or an https URL.

        The agent is supposed to pass `image_url` (signed https), but Gemini
        sometimes hands us `gcs_uri` (gs://) by mistake. Accept both rather
        than silently failing.
        """
        try:
            if url.startswith("gs://"):
                from google.cloud import storage as _gcs
                no_scheme = url[5:]
                bucket_name, _, key = no_scheme.partition("/")
                blob = _gcs.Client().bucket(bucket_name).blob(key)
                content = blob.download_as_bytes()
                content_type = blob.content_type or ""
            else:
                import requests
                resp = requests.get(url, timeout=30)
                resp.raise_for_status()
                content = resp.content
                content_type = resp.headers.get("Content-Type", "")

            ext = ".jpg"
            if ".png" in url.lower() or "png" in content_type:
                ext = ".png"
            img_path = save_dir / f"product_image{ext}"
            with open(img_path, "wb") as f:
                f.write(content)
            logger.info(
                f"download_image OK: {img_path} ({len(content)} bytes from "
                f"{'gs://' if url.startswith('gs://') else 'https'})"
            )
            return True
        except Exception as e:
            logger.error(
                f"download_image FAILED for {url[:120]}...: {type(e).__name__}: {e}"
            )
            return False

    xl = pd.ExcelFile(excel_path)
    data_path = Path(data_dir)
    data_path.mkdir(parents=True, exist_ok=True)

    # Check if Excel has a company_name column
    has_company_col = False  # determined per-sheet below

    summary = {"categories": {}, "total_created": 0, "total_skipped": 0, "default_company_name": company_name}

    for sheet_name in xl.sheet_names:
        df = pd.read_excel(xl, sheet_name=sheet_name)
        has_company_col = "company_name" in df.columns
        cat_folder = sanitize_folder_name(sheet_name)
        cat_path = data_path / cat_folder
        cat_path.mkdir(exist_ok=True)

        # In append mode, filter out existing products
        if append:
            existing = {d.name for d in cat_path.iterdir() if d.is_dir()}
            df["_pid"] = df["product_id"].astype(str)
            before = len(df)
            df = df[~df["_pid"].isin(existing)]
            skipped = before - len(df)
            df = df.drop(columns=["_pid"])
        else:
            skipped = 0

        if sample_counts and sample_counts < len(df):
            df = df.sample(n=sample_counts)

        created = 0
        for _, row in df.iterrows():
            pid = str(row["product_id"])
            product_path = cat_path / pid
            product_path.mkdir(exist_ok=True)

            country_raw = str(row.get("country", "US"))
            lang_raw = str(row.get("language", "en"))

            # Per-product company_name: Excel column > parameter > settings default
            row_company = None
            if has_company_col:
                raw = row.get("company_name")
                if raw and str(raw).strip() and str(raw) != "nan":
                    row_company = str(raw).strip()
            product_company = row_company or company_name

            # Resolve country/language — accept both codes and full names
            country_resolved = country_map.get(country_raw.upper(), country_raw)
            lang_resolved = language_map.get(lang_raw.lower(), lang_raw)

            metadata = {
                "product_id": pid,
                "country": country_resolved,
                "product_desc": str(row.get("product_name", "")),
                "language": lang_resolved,
                "company_name": product_company,
                "image_url": str(row.get("image_url", "")),
            }
            with open(product_path / "metadata.json", "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=4, ensure_ascii=False)

            img_url = row.get("image_url", "")
            if img_url and str(img_url) != "nan":
                download_image(str(img_url), product_path)

            # Upload product data (metadata.json + images) to GCS for cloud access
            user_id = _get_user_id()
            set_user_id(user_id)
            gcs_data_prefix = f"{get_gcs_prefix()}/data/{cat_folder}/{pid}"
            gcs_service.upload_product_data(str(product_path), gcs_data_prefix)
            logger.info(f"Uploaded product data to GCS: {gcs_data_prefix}")

            created += 1

        summary["categories"][sheet_name] = {"folder": cat_folder, "created": created, "skipped": skipped}
        summary["total_created"] += created
        summary["total_skipped"] += skipped

    return summary


# ── MCP Resources ─────────────────────────────────────────────────────────────

@mcp.resource("pipeline://config")
def get_pipeline_config() -> str:
    """Get current pipeline configuration."""
    config = {
        "execution_mode": EXECUTION_MODE,
        "veo_model": settings.VEO_MODEL_VERSION,
        "gemini_pro": settings.GEMINI_MODEL_PRO,
        "gemini_image": settings.GEMINI_MODEL_IMAGE,
        "default_company": settings.DEFAULT_COMPANY_NAME,
        "output_dir": settings.TEMP_OUTPUT_DIR,
        "default_aspect_ratio": settings.VEO_DEFAULT_ASPECT_RATIO,
    }
    return json.dumps(config, indent=2)


@mcp.resource("pipeline://products/{data_dir}")
def get_products_resource(data_dir: str) -> str:
    """Get product listing as a resource."""
    products = list_products(data_dir)
    return json.dumps(products, indent=2)


# ── Background Execution (local mode only) ───────────────────────────────────


def _run_pipeline_local(job_id: str, params: dict):
    """Execute pipeline locally in background thread."""
    mode = params["mode"]
    data_dir = params["data_dir"]
    product_ids = params.get("product_ids")
    company_name = params.get("company_name")
    max_sample_images = params.get("max_sample_images")  # None → orchestrator falls back to settings.MAX_SAMPLE_IMAGES
    max_sample_clips = params.get("max_sample_clips")    # None → orchestrator falls back to settings.MAX_SAMPLE_CLIPS
    max_workers = params.get("max_workers", 1)
    force = params.get("force", False)
    aspect_ratio = params.get("aspect_ratio", "16:9")

    # Set user context for this thread so output is scoped by user_id
    user_id = params.get("user_id", "anonymous")
    set_user_id(user_id)

    job_manager.update_job_status(job_id, JobStatus.RUNNING)

    try:
        if product_ids:
            results = _process_specific_products(
                job_id, product_ids, data_dir, mode,
                company_name, max_sample_images, max_sample_clips,
                force, aspect_ratio, max_workers,
            )
        else:
            if mode == "image_only":
                results = batch_process_image_only(
                    data_dir=data_dir, company_name=company_name,
                    max_workers=max_workers, max_sample_images=max_sample_images,
                    force=force,
                )
            else:
                results = batch_process(
                    data_dir=data_dir, company_name=company_name,
                    max_workers=max_workers, max_sample_images=max_sample_images,
                    max_sample_clips=max_sample_clips, force=force,
                )
        job_manager.update_job_status(job_id, JobStatus.COMPLETED, result=results)
    except Exception as e:
        logger.error(f"Job {job_id} failed: {e}", exc_info=True)
        job_manager.update_job_status(job_id, JobStatus.FAILED, error=str(e))


def _process_specific_products(
    job_id, product_ids, data_dir, mode,
    company_name, max_sample_images, max_sample_clips,
    force, aspect_ratio, max_workers,
):
    """Process specific product IDs locally."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from mcp_server.pipeline.user_context import get_user_id

    # Capture current user_id to propagate to worker threads
    current_user_id = get_user_id()

    results = {"success": [], "failed": [], "skipped": [], "total": len(product_ids)}

    # Build product dir map using get_all_product_directories (supports GCS fallback)
    set_user_id(current_user_id)
    all_product_dirs = get_all_product_directories(data_dir)
    dir_map = {}
    for product_dir in all_product_dirs:
        product_id = os.path.basename(product_dir)
        dir_map[product_id] = product_dir

    def process_one(pid):
        # Propagate user context to worker thread
        set_user_id(current_user_id)
        product_dir = dir_map.get(pid)
        if not product_dir:
            return {"product_id": pid, "error": f"Product '{pid}' not found in {data_dir}"}
        job = job_manager.get_job(job_id)
        if job and job.is_cancelled:
            return {"product_id": pid, "skipped": True, "reason": "Job cancelled"}
        if mode == "image_only":
            return process_product_image_only(
                product_directory=product_dir, company_name=company_name,
                max_sample_images=max_sample_images, force=force,
                aspect_ratio=aspect_ratio,
            )
        else:
            return process_product(
                product_directory=product_dir, company_name=company_name,
                max_sample_images=max_sample_images, max_sample_clips=max_sample_clips,
                force=force, aspect_ratio=aspect_ratio,
            )

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_pid = {executor.submit(process_one, pid): pid for pid in product_ids}
        for future in as_completed(future_to_pid):
            pid = future_to_pid[future]
            try:
                result = future.result()
                if result:
                    if result.get("skipped"):
                        results["skipped"].append(result)
                    elif result.get("error"):
                        results["failed"].append(result)
                    else:
                        results["success"].append(result)
                else:
                    results["failed"].append({"product_id": pid, "error": "Pipeline returned None"})
            except Exception as e:
                results["failed"].append({"product_id": pid, "error": str(e)})

            completed = len(results["success"]) + len(results["failed"]) + len(results["skipped"])
            job_manager.update_job_status(
                job_id, JobStatus.RUNNING,
                progress={"completed": completed, "total": results["total"]},
            )

    return results


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    """Run the MCP server."""
    import argparse

    parser = argparse.ArgumentParser(description="Ads Video Pipeline MCP Server")
    parser.add_argument(
        "--transport", choices=["stdio", "streamable-http"],
        default="streamable-http", help="MCP transport type (default: streamable-http)",
    )
    parser.add_argument("--host", default="0.0.0.0", help="Host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080, help="Port (default: 8080)")
    args = parser.parse_args()

    # host/port are set on the FastMCP instance (constructor params), not run()
    mcp._host = args.host  # type: ignore[attr-defined]
    mcp._port = args.port  # type: ignore[attr-defined]
    # Also set via the settings object that FastMCP actually reads
    mcp.settings.host = args.host
    mcp.settings.port = args.port

    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
