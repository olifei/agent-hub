"""
Cloud Run Jobs integration for dispatching pipeline work.

The MCP server (Cloud Run Service) submits pipeline executions as
Cloud Run Jobs, then tracks their status via the Cloud Run Jobs API.

Architecture:
  MCP Client → Cloud Run Service (MCP Server) → Cloud Run Job (Pipeline)
                      ↑                                ↓
                      └─── get_job_status ← Jobs API ──┘
                      └─── get_job_logs  ← Cloud Logging ─┘
"""

import os
import json
import logging
from typing import Optional

from google.cloud import run_v2

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

PROJECT_ID = os.environ.get("VERTEX_AI_PROJECT_ID", "")
REGION = os.environ.get("VERTEX_AI_LOCATION", "us-central1")
PIPELINE_JOB_NAME = os.environ.get("PIPELINE_JOB_NAME", "ads-video-pipeline-job")


def get_jobs_client() -> run_v2.JobsClient:
    """Get Cloud Run Jobs client."""
    return run_v2.JobsClient()


def get_executions_client() -> run_v2.ExecutionsClient:
    """Get Cloud Run Executions client."""
    return run_v2.ExecutionsClient()


def job_id_from_execution_name(execution_name: str) -> str:
    """Extract the agent-facing job_id from a Cloud Run execution resource name.

    The job_id is the 5-char suffix Cloud Run appends, e.g. "bw79s" from
    "projects/P/locations/R/jobs/ads-video-pipeline-job/executions/ads-video-pipeline-job-bw79s".
    """
    short_name = execution_name.rsplit("/", 1)[-1]
    return short_name.rsplit("-", 1)[-1]


def execution_name_from_job_id(job_id: str) -> str:
    """Reconstruct the full Cloud Run execution resource name from a job_id suffix."""
    return (
        f"projects/{PROJECT_ID}/locations/{REGION}"
        f"/jobs/{PIPELINE_JOB_NAME}/executions/{PIPELINE_JOB_NAME}-{job_id}"
    )


def submit_pipeline_job(
    mode: str,
    data_dir: str,
    product_ids: list[str] = None,
    company_name: str = None,
    max_sample_images: int = 1,
    max_sample_clips: int = 1,
    force: bool = False,
    aspect_ratio: str = "16:9",
    user_id: str = "anonymous",
) -> dict:
    """Submit a pipeline execution as a Cloud Run Job.

    Creates an execution of the pre-deployed Cloud Run Job template,
    passing pipeline parameters as environment variable overrides.

    Args:
        mode: Pipeline mode (full, image_only, video_only)
        data_dir: Data directory path
        product_ids: Optional list of product IDs
        company_name: Company name
        max_sample_images: Max image attempts
        max_sample_clips: Max clip attempts
        force: Force re-processing
        aspect_ratio: Target aspect ratio
        user_id: User who submitted the job
        job_id: MCP job tracking ID

    Returns:
        dict with execution_name and status
    """
    jobs_client = get_jobs_client()

    job_name = f"projects/{PROJECT_ID}/locations/{REGION}/jobs/{PIPELINE_JOB_NAME}"

    # Pipeline params as JSON env var. The pipeline_runner derives its own
    # job_id from $CLOUD_RUN_EXECUTION (set automatically by Cloud Run), so
    # we don't pre-allocate one here.
    pipeline_params = json.dumps({
        "mode": mode,
        "data_dir": data_dir,
        "product_ids": product_ids,
        "company_name": company_name,
        "max_sample_images": max_sample_images,
        "max_sample_clips": max_sample_clips,
        "force": force,
        "aspect_ratio": aspect_ratio,
        "user_id": user_id,
    })

    overrides = run_v2.RunJobRequest.Overrides(
        container_overrides=[
            run_v2.RunJobRequest.Overrides.ContainerOverride(
                env=[
                    run_v2.EnvVar(name="PIPELINE_PARAMS", value=pipeline_params),
                    run_v2.EnvVar(name="USER_ID", value=user_id),
                    # Force stdout flush so STEP banners stream to Cloud
                    # Logging in real-time instead of buffering until exit.
                    run_v2.EnvVar(name="PYTHONUNBUFFERED", value="1"),
                ],
            )
        ],
    )

    request = run_v2.RunJobRequest(
        name=job_name,
        overrides=overrides,
    )

    try:
        operation = jobs_client.run_job(request=request)
        execution_name = operation.metadata.name if hasattr(operation, "metadata") else ""
        job_id = job_id_from_execution_name(execution_name) if execution_name else ""

        logger.info(f"Submitted Cloud Run Job execution: {execution_name} (job_id={job_id})")
        return {
            "job_id": job_id,
            "execution_name": execution_name,
            "status": "submitted",
            "job_name": job_name,
        }
    except Exception as e:
        logger.error(f"Failed to submit Cloud Run Job: {e}")
        raise


def get_execution_status(execution_name: str) -> dict:
    """Get the status of a Cloud Run Job execution.

    Args:
        execution_name: Full execution resource name

    Returns:
        dict with status, start_time, completion_time, etc.
    """
    if not execution_name:
        return {"status": "unknown", "error": "No execution name"}

    try:
        client = get_executions_client()
        execution = client.get_execution(name=execution_name)

        # Map Cloud Run execution conditions to simple status
        status = "running"
        error = None

        for condition in execution.conditions:
            if condition.type_ == "Completed":
                if condition.state == run_v2.Condition.State.CONDITION_SUCCEEDED:
                    status = "completed"
                elif condition.state == run_v2.Condition.State.CONDITION_FAILED:
                    status = "failed"
                    error = condition.message
                break

        return {
            "status": status,
            "execution_name": execution_name,
            "start_time": execution.start_time.isoformat() if execution.start_time else None,
            "completion_time": execution.completion_time.isoformat() if execution.completion_time else None,
            "error": error,
            "task_count": execution.task_count,
            "succeeded_count": execution.succeeded_count,
            "failed_count": execution.failed_count,
        }
    except Exception as e:
        logger.error(f"Failed to get execution status: {e}")
        return {"status": "unknown", "error": str(e)}


def get_execution_logs(
    execution_name: str,
    max_entries: int = 50,
    severity_min: str = "DEFAULT",
) -> list[dict]:
    """Fetch Cloud Logging entries for a Cloud Run Job execution.

    Queries structured logs written by the pipeline runner container.
    Filters by the execution resource name to get only relevant logs.

    Args:
        execution_name: Full execution resource name
            (e.g. "projects/P/locations/R/jobs/J/executions/E")
        max_entries: Maximum number of log entries to return (default: 50)
        severity_min: Minimum severity level (DEFAULT, INFO, WARNING, ERROR)

    Returns:
        List of log entry dicts with timestamp, severity, and message.
    """
    if not execution_name:
        return []

    try:
        from google.cloud import logging as cloud_logging

        client = cloud_logging.Client(project=PROJECT_ID)

        # Extract execution ID from full resource name
        # e.g. "projects/P/locations/R/jobs/J/executions/E" → "E"
        parts = execution_name.split("/")
        execution_id = parts[-1] if parts else execution_name
        job_name_part = parts[-3] if len(parts) >= 4 else PIPELINE_JOB_NAME

        # Cloud Run Job logs use these labels:
        #   resource.type = "cloud_run_job"
        #   resource.labels.job_name = "ads-video-pipeline-job"
        #   labels."run.googleapis.com/execution_name" = execution_id
        log_filter = (
            f'resource.type="cloud_run_job" '
            f'resource.labels.job_name="{job_name_part}" '
            f'labels."run.googleapis.com/execution_name"="{execution_id}" '
            f'severity>={severity_min}'
        )

        # Query newest-first so a long-running job's latest STEP/attempt
        # lines aren't truncated; reverse before returning so callers see
        # oldest-first within the window (preserves last-match-wins
        # ordering in agent-side _latest_stage parsing).
        entries = list(client.list_entries(
            filter_=log_filter,
            order_by=cloud_logging.DESCENDING,
            max_results=max_entries,
        ))
        entries.reverse()

        log_lines = []
        for entry in entries:
            # Extract message from different log payload types
            if isinstance(entry.payload, dict):
                message = entry.payload.get("message", entry.payload.get("textPayload", str(entry.payload)))
            elif isinstance(entry.payload, str):
                message = entry.payload
            else:
                message = str(entry.payload)

            log_lines.append({
                "timestamp": entry.timestamp.isoformat() if entry.timestamp else "",
                "severity": entry.severity or "DEFAULT",
                "message": message,
            })

        return log_lines

    except ImportError:
        logger.warning("google-cloud-logging not installed, cannot fetch logs")
        return [{"timestamp": "", "severity": "WARNING", "message": "google-cloud-logging not installed"}]
    except Exception as e:
        logger.error(f"Failed to fetch execution logs: {e}")
        return [{"timestamp": "", "severity": "ERROR", "message": f"Failed to fetch logs: {e}"}]


def list_executions(max_results: int = 50) -> list[dict]:
    """List recent executions of the pipeline Cloud Run Job."""
    try:
        client = get_executions_client()
        parent = f"projects/{PROJECT_ID}/locations/{REGION}/jobs/{PIPELINE_JOB_NAME}"
        request = run_v2.ListExecutionsRequest(parent=parent, page_size=max_results)
        pager = client.list_executions(request=request)
        out: list[dict] = []
        for execution in pager:
            if len(out) >= max_results:
                break
            out.append(_execution_to_dict(execution))
        return out
    except Exception as e:
        logger.error(f"Failed to list executions: {e}")
        return []


def cancel_execution(execution_name: str) -> dict:
    """Cancel a running Cloud Run Job execution."""
    if not execution_name:
        return {"status": "unknown", "error": "No execution name"}
    try:
        client = get_executions_client()
        op = client.cancel_execution(name=execution_name)
        op.result(timeout=30)
        return get_execution_status(execution_name)
    except Exception as e:
        logger.error(f"Failed to cancel execution: {e}")
        return {"status": "unknown", "error": str(e)}


def _execution_to_dict(execution) -> dict:
    """Translate a run_v2.Execution proto into a JSON-safe summary dict."""
    status = "running"
    error = None
    for condition in execution.conditions:
        if condition.type_ == "Completed":
            if condition.state == run_v2.Condition.State.CONDITION_SUCCEEDED:
                status = "completed"
            elif condition.state == run_v2.Condition.State.CONDITION_FAILED:
                status = "failed"
                error = condition.message
            elif condition.state == run_v2.Condition.State.CONDITION_CANCELLED:
                status = "cancelled"
            break
    user_id = ""
    if execution.template and execution.template.containers:
        for env in execution.template.containers[0].env:
            if env.name == "USER_ID":
                user_id = env.value
                break
    return {
        "job_id": job_id_from_execution_name(execution.name),
        "execution_name": execution.name,
        "status": status,
        "user_id": user_id,
        "created_at": execution.create_time.isoformat() if execution.create_time else None,
        "start_time": execution.start_time.isoformat() if execution.start_time else None,
        "completion_time": (
            execution.completion_time.isoformat() if execution.completion_time else None
        ),
        "task_count": execution.task_count,
        "succeeded_count": execution.succeeded_count,
        "failed_count": execution.failed_count,
        "error": error,
    }


def get_execution_pipeline_params(execution_name: str) -> dict:
    """Read the PIPELINE_PARAMS env var off the execution to recover mode/params."""
    if not execution_name:
        return {}
    try:
        execution = get_executions_client().get_execution(name=execution_name)
        if execution.template and execution.template.containers:
            for env in execution.template.containers[0].env:
                if env.name == "PIPELINE_PARAMS" and env.value:
                    return json.loads(env.value)
    except Exception as e:
        logger.warning(f"Could not read PIPELINE_PARAMS for {execution_name}: {e}")
    return {}


def read_job_result(job_id: str, gcs_prefix: str, bucket_name: str) -> Optional[dict]:
    """Read the pipeline_runner's result.json for a completed job from GCS.

    The pipeline_runner writes to
    `gs://{bucket}/{gcs_prefix}/_job_results/{job_id}.json` on exit.
    Returns None if the file doesn't exist (job still running, or no result yet).
    """
    if not job_id or not bucket_name:
        return None
    try:
        from google.cloud import storage as gcs_storage

        key = f"{gcs_prefix.rstrip('/')}/_job_results/{job_id}.json"
        blob = gcs_storage.Client().bucket(bucket_name).blob(key)
        if not blob.exists():
            return None
        return json.loads(blob.download_as_text())
    except Exception as e:
        logger.warning(f"Could not read job result for {job_id}: {e}")
        return None
