"""
Pipeline Runner — Entry point for Cloud Run Job execution.

This runs inside the Cloud Run Job container. It reads pipeline
parameters from the PIPELINE_PARAMS environment variable and
executes the pipeline, writing results to GCS.

Usage (Cloud Run Job):
  python -m mcp_server.pipeline_runner

The PIPELINE_PARAMS env var contains JSON:
  {
    "mode": "full",
    "data_dir": "data/luggage_bags_cases",
    "product_ids": ["1601442859214"],
    "max_sample_images": 1,
    "max_sample_clips": 1,
    ...
  }
"""

import os
import sys
import json
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def main():
    """Execute pipeline from Cloud Run Job environment variables."""
    params_json = os.environ.get("PIPELINE_PARAMS")
    if not params_json:
        logger.error("PIPELINE_PARAMS environment variable not set")
        sys.exit(1)

    try:
        params = json.loads(params_json)
    except json.JSONDecodeError as e:
        logger.error(f"Invalid PIPELINE_PARAMS JSON: {e}")
        sys.exit(1)

    mode = params.get("mode", "full")
    data_dir = params.get("data_dir", "data")
    product_ids = params.get("product_ids")
    company_name = params.get("company_name")
    max_sample_images = params.get("max_sample_images", 1)
    max_sample_clips = params.get("max_sample_clips", 1)
    force = params.get("force", False)
    aspect_ratio = params.get("aspect_ratio", "16:9")
    user_id = params.get("user_id", "anonymous")

    # job_id is the Cloud Run execution suffix (Cloud Run sets CLOUD_RUN_EXECUTION
    # to the full execution short-name, e.g. "ads-video-pipeline-job-bw79s").
    # Fall back to legacy MCP_JOB_ID or PIPELINE_PARAMS["mcp_job_id"] for back-compat.
    mcp_job_id = (
        os.environ.get("CLOUD_RUN_EXECUTION", "").rsplit("-", 1)[-1]
        or os.environ.get("MCP_JOB_ID", "")
        or params.get("mcp_job_id", "")
    )

    logger.info(f"Pipeline Runner starting: mode={mode}, user={user_id}, job={mcp_job_id}")
    logger.info(f"  data_dir={data_dir}, products={product_ids}")

    # Set user context for output/GCS path scoping
    from mcp_server.pipeline.user_context import set_user_id, get_output_base_dir, get_gcs_prefix
    from mcp_server.pipeline.gcs_service import gcs_service
    set_user_id(user_id)
    logger.info(f"  output_base_dir={get_output_base_dir()}")

    # Import pipeline modules
    from mcp_server.pipeline.orchestrator import (
        process_product,
        process_product_image_only,
        batch_process,
        batch_process_image_only,
        get_all_product_directories,
    )

    try:
        if product_ids:
            # Process specific products
            results = _process_specific(
                product_ids, data_dir, mode,
                company_name, max_sample_images, max_sample_clips,
                force, aspect_ratio,
            )
        else:
            # Batch all products in data_dir
            if mode == "image_only":
                results = batch_process_image_only(
                    data_dir=data_dir,
                    company_name=company_name,
                    max_sample_images=max_sample_images,
                    force=force,
                )
            else:
                results = batch_process(
                    data_dir=data_dir,
                    company_name=company_name,
                    max_sample_images=max_sample_images,
                    max_sample_clips=max_sample_clips,
                    force=force,
                )

        # Write results to a known location for the MCP server to read
        results_base = f"{get_output_base_dir()}/_job_results"
        results_path = f"{results_base}/{mcp_job_id or 'latest'}.json"
        os.makedirs(os.path.dirname(results_path), exist_ok=True)
        with open(results_path, "w") as f:
            json.dump({"status": "completed", "results": results, "user_id": user_id}, f, indent=2, default=str)

        # Upload job results to GCS for the MCP server to retrieve
        gcs_results_key = f"{get_gcs_prefix()}/_job_results/{mcp_job_id or 'latest'}.json"
        gcs_service.upload_file(results_path, gcs_results_key, replace=True)
        logger.info(f"Job results uploaded to GCS: {gcs_results_key}")

        logger.info(f"Pipeline completed. Results: {len(results.get('success', []))} success, {len(results.get('failed', []))} failed")

    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
        # Write error result
        results_base = f"{get_output_base_dir()}/_job_results"
        results_path = f"{results_base}/{mcp_job_id or 'latest'}.json"
        os.makedirs(os.path.dirname(results_path), exist_ok=True)
        with open(results_path, "w") as f:
            json.dump({"status": "failed", "error": str(e), "user_id": user_id}, f, indent=2)

        # Upload error results to GCS
        gcs_results_key = f"{get_gcs_prefix()}/_job_results/{mcp_job_id or 'latest'}.json"
        gcs_service.upload_file(results_path, gcs_results_key, replace=True)
        logger.info(f"Error results uploaded to GCS: {gcs_results_key}")

        sys.exit(1)


def _process_specific(product_ids, data_dir, mode, company_name,
                      max_sample_images, max_sample_clips, force, aspect_ratio):
    """Process specific product IDs.
    
    Uses get_all_product_directories which supports both local filesystem
    and GCS data store fallback (critical for Cloud Run Jobs where data
    is only in GCS, not on the local filesystem).
    """
    from mcp_server.pipeline.orchestrator import (
        process_product, process_product_image_only, get_all_product_directories,
    )

    # Build product directory map using get_all_product_directories
    # This supports GCS fallback when local data doesn't exist (Cloud Run Jobs)
    all_product_dirs = get_all_product_directories(data_dir)
    dir_map = {}
    for product_dir in all_product_dirs:
        product_id = os.path.basename(product_dir)
        dir_map[product_id] = product_dir
    logger.info(f"Product directory map: {dir_map}")

    results = {"success": [], "failed": [], "skipped": [], "total": len(product_ids)}

    for pid in product_ids:
        product_dir = dir_map.get(pid)
        if not product_dir:
            results["failed"].append({"product_id": pid, "error": f"Not found in {data_dir}"})
            continue

        try:
            if mode == "image_only":
                result = process_product_image_only(
                    product_directory=product_dir,
                    company_name=company_name,
                    max_sample_images=max_sample_images,
                    force=force,
                    aspect_ratio=aspect_ratio,
                )
            else:
                result = process_product(
                    product_directory=product_dir,
                    company_name=company_name,
                    max_sample_images=max_sample_images,
                    max_sample_clips=max_sample_clips,
                    force=force,
                    aspect_ratio=aspect_ratio,
                )

            if result and not result.get("error"):
                if result.get("skipped"):
                    results["skipped"].append(result)
                else:
                    results["success"].append(result)
            else:
                results["failed"].append({"product_id": pid, "error": str(result)})
        except Exception as e:
            results["failed"].append({"product_id": pid, "error": str(e)})

    return results


if __name__ == "__main__":
    main()
