# ruff: noqa
"""Agent-side helper tools.

These run in the agent process (not the MCP server). They wrap MCP calls,
GCS reads/writes, and Excel normalization so the LLM doesn't have to drive
slow polling loops or construct multipart media itself.
"""

from __future__ import annotations

import ast
import asyncio
import io
import json
import logging
import os
import re
import time
import uuid
from datetime import timedelta
from typing import Optional

import pandas as pd
from google.adk.tools.tool_context import ToolContext
from google.auth import default as google_auth_default
from google.auth.transport.requests import Request
from google.cloud import storage
from google.genai import types

from .mcp_client import call_mcp_tool

_log = logging.getLogger(__name__)

_TERMINAL = {"completed", "failed", "cancelled"}
_STEP_RE = re.compile(r"STEP\s+(\d+)\s*:\s*(.+)", re.IGNORECASE)
_PASS_FAIL_RE = re.compile(r"\b(\d+)\s*/\s*(\d+)\s+criteria\s+passed\b", re.IGNORECASE)
_ATTEMPT_HEADER_RE = re.compile(
    r"\b(?:Image|Video|Clip)\s+generation\s+attempt\s+(\d+)\s*/\s*(\d+)\b",
    re.IGNORECASE,
)
_ATTEMPT_FAIL_RE = re.compile(
    r"criteria\s+failed\s+on\s+attempt\s+(\d+)\s*:\s*(\[[^\]]+\])", re.IGNORECASE
)
_ATTEMPT_PASS_RE = re.compile(
    r"All\s+\w+\s+criteria\s+passed\s+on\s+attempt\s+(\d+)", re.IGNORECASE
)
_CONTENT_POLICY_RE = re.compile(r"content\s+policy\s+violation", re.IGNORECASE)
_HIGH_LOAD_RE = re.compile(r"high\s+load", re.IGNORECASE)


# ─── wait_for_job ────────────────────────────────────────────────────────────


async def wait_for_job(job_id: str, timeout_s: int = 60, poll_s: int = 15) -> dict:
    """Wait up to `timeout_s` seconds (capped at 60) for a pipeline job to
    reach a terminal state (completed/failed/cancelled).

    Use this after batch_generate. Returns the final job status dict with
    `stage` populated from the latest STEP banner in the job logs so the
    caller can surface progress without an extra round-trip. If the cap
    elapses before the job finishes, returns with status='running' and
    timed_out=True so the caller MUST re-invoke. The cap is enforced
    server-side so the agent can't accidentally block for longer than
    one minute per call.
    """
    timeout_s = min(timeout_s, 60)
    deadline = time.monotonic() + timeout_s
    last = await call_mcp_tool("get_job_status", {"job_id": job_id})
    while last.get("status") not in _TERMINAL and time.monotonic() < deadline:
        await asyncio.sleep(poll_s)
        last = await call_mcp_tool("get_job_status", {"job_id": job_id})
    last["timed_out"] = last.get("status") not in _TERMINAL
    last["stage"], last["last_evaluation"] = await _latest_stage(job_id)
    return last


async def _latest_stage(job_id: str) -> tuple[str, Optional[str]]:
    """Scan the job's logs and return (stage, last_evaluation).

    `stage` combines the latest STEP banner with the current attempt number
    (e.g. "STEP 1: Generating Starting Frame Image — Attempt 2/3") and the
    most recent attempt outcome (e.g. "(attempt 1 failed: detail_preservation,
    realism)") so the agent can surface iterative progress without an extra
    round-trip.
    """
    logs = await call_mcp_tool(
        "get_job_logs", {"job_id": job_id, "max_entries": 200, "severity": "DEFAULT"}
    )
    entries = logs.get("logs", []) if isinstance(logs, dict) else []
    latest_step: Optional[str] = None
    latest_eval: Optional[str] = None
    current_attempt: Optional[tuple[int, int]] = None
    last_outcome: Optional[str] = None
    for entry in entries:
        msg = entry.get("message") if isinstance(entry, dict) else str(entry)
        if not msg:
            continue
        m = _STEP_RE.search(msg)
        if m:
            latest_step = f"STEP {m.group(1)}: {m.group(2).strip()}"
            current_attempt = None  # reset attempt count for the new STEP
            last_outcome = None
        if _PASS_FAIL_RE.search(msg):
            latest_eval = msg.strip()
        m = _ATTEMPT_HEADER_RE.search(msg)
        if m:
            current_attempt = (int(m.group(1)), int(m.group(2)))
        m = _ATTEMPT_FAIL_RE.search(msg)
        if m:
            crits = m.group(2).replace("'", "").replace('"', "").strip("[] ")
            last_outcome = f"attempt {m.group(1)} failed: {crits}"
            continue
        m = _ATTEMPT_PASS_RE.search(msg)
        if m:
            last_outcome = f"attempt {m.group(1)} passed"
            continue
        if _CONTENT_POLICY_RE.search(msg) and current_attempt:
            last_outcome = f"attempt {current_attempt[0]} content policy violation, retrying"
        elif _HIGH_LOAD_RE.search(msg) and current_attempt:
            last_outcome = f"attempt {current_attempt[0]} service busy, retrying"

    stage = latest_step or "(no STEP banner yet — pipeline starting)"
    if current_attempt:
        stage += f" — Attempt {current_attempt[0]}/{current_attempt[1]}"
    if last_outcome:
        stage += f" ({last_outcome})"
    return stage, latest_eval


# ─── report_job_progress ─────────────────────────────────────────────────────


async def report_job_progress(job_id: str) -> dict:
    """Summarize the high-level pipeline stage from job logs.

    Calls get_job_logs and distills the orchestrator's STEP banners and the
    evaluator's pass/fail summary lines into a one-line status the agent can
    relay to the user. Use before wait_for_job (to set expectations) and
    on-demand when the user asks "how's it going?".
    """
    status = await call_mcp_tool("get_job_status", {"job_id": job_id})
    stage, last_evaluation = await _latest_stage(job_id)
    return {
        "job_id": job_id,
        "status": status.get("status"),
        "stage": stage,
        "last_evaluation": last_evaluation,
    }


# ─── fetch_image_bytes ───────────────────────────────────────────────────────

_MIME_BY_EXT = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


def _parse_gs(uri: str) -> tuple[str, str]:
    if not uri.startswith("gs://"):
        raise ValueError(f"Not a gs:// URI: {uri}")
    bucket, _, key = uri[5:].partition("/")
    return bucket, key


async def fetch_image_bytes(gcs_uri: str, tool_context: ToolContext) -> dict:
    """Download an image from GCS and save it as an inline artifact.

    The artifact is then surfaced inline in the agent's response. Returns the
    artifact filename for the agent to reference.
    """
    bucket, key = _parse_gs(gcs_uri)
    blob = storage.Client().bucket(bucket).blob(key)
    data = blob.download_as_bytes()
    ext = os.path.splitext(key)[1].lower()
    mime = _MIME_BY_EXT.get(ext, "image/png")

    filename = f"{os.path.basename(key)}"
    await tool_context.save_artifact(
        filename, types.Part(inline_data=types.Blob(data=data, mime_type=mime))
    )
    return {
        "artifact_filename": filename,
        "mime_type": mime,
        "size_bytes": len(data),
        "gcs_uri": gcs_uri,
    }


# ─── presign_video_url ───────────────────────────────────────────────────────


def _make_signed_url(gcs_uri: str, expires_min: int) -> str:
    """Generate a V4 signed HTTPS URL for a private GCS object via IAM signBlob.

    Validates the resulting signature with a HEAD request and retries once
    after refreshing credentials. Transient SignatureDoesNotMatch responses
    from signBlob have been observed on the first call after a cold start.
    """
    bucket_name, key = _parse_gs(gcs_uri)
    creds, _ = google_auth_default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    blob = storage.Client().bucket(bucket_name).blob(key)

    def _sign() -> str:
        creds.refresh(Request())
        sa_email = os.environ.get("MCP_IMPERSONATE_SA") or getattr(
            creds, "service_account_email", None
        )
        if not sa_email:
            raise RuntimeError(
                "Cannot determine signer SA. Set MCP_IMPERSONATE_SA for local dev "
                "or run on a runtime with SA credentials."
            )
        return blob.generate_signed_url(
            version="v4",
            expiration=timedelta(minutes=expires_min),
            method="GET",
            service_account_email=sa_email,
            access_token=creds.token,
        )

    import httpx
    for attempt in range(2):
        url = _sign()
        try:
            r = httpx.head(url, timeout=10.0, follow_redirects=False)
            if r.status_code != 403:
                return url
        except httpx.HTTPError as e:
            _log.warning("presign HEAD failed (attempt %d): %s", attempt + 1, e)
            return url
        _log.warning("presign HEAD got 403 on attempt %d, resigning", attempt + 1)
    return url


def presign_video_url(gcs_uri: str, expires_min: int = 60) -> dict:
    """Create a V4 signed URL for a private GCS video so the user can play it
    in a new tab. Uses IAM signBlob (no SA key needed) — works with both user
    ADC + impersonation locally and SA creds in production.
    """
    return {
        "signed_url": _make_signed_url(gcs_uri, expires_min),
        "expires_min": expires_min,
        "gcs_uri": gcs_uri,
    }


# ─── save_uploaded_file ──────────────────────────────────────────────────────

_EXT_BY_MIME = {
    # images
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    # datasets
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-excel": ".xls",
    "text/csv": ".csv",
    "application/csv": ".csv",
    "application/json": ".json",
    "text/json": ".json",
}

_DATASET_MIMES = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "text/csv",
    "application/csv",
    "application/json",
    "text/json",
}


def _mime_matches_kind(mime: str, file_kind: str) -> bool:
    if file_kind == "image":
        return mime.startswith("image/")
    if file_kind == "dataset":
        return mime in _DATASET_MIMES
    return False


async def save_uploaded_file(
    tool_context: ToolContext,
    file_kind: str,
    filename: Optional[str] = None,
    filename_hint: str = "upload",
) -> dict:
    """Save the latest user-uploaded file from this conversation to GCS.

    Use this when the user attaches a file directly to chat instead of
    providing a URI. Tries three paths in order:
      1. If `filename` is provided, load that named ADK artifact (this is
         how Gemini Enterprise UI passes uploads — as named artifacts).
      2. Otherwise, list session artifacts and pick the most recent one
         whose extension matches `file_kind`.
      3. Fall back to scanning the user's content / event Parts for raw
         `inline_data` or `file_data` (this is how the cloud playground
         and direct A2A clients pass uploads).

    Args:
      file_kind: "image" for product images (use the returned `gs://`
        URI as the `image_url` field of a product dict). "dataset" for
        xlsx / csv / json catalogs (pass the returned URI to
        `prepare_dataset(source_uri=...)`).
      filename: the artifact filename if the user mentioned one in chat
        (e.g. "product1.jpg"). Strongly recommended on Gemini Enterprise
        — the user's text usually names the attached file.
      filename_hint: short slug used in the GCS object key.
    """
    if file_kind not in {"image", "dataset"}:
        return {"error": f"Unsupported file_kind: {file_kind}"}

    inv = tool_context._invocation_context

    def _fetch_uri(uri: str) -> bytes:
        if uri.startswith("gs://"):
            bucket, key = _parse_gs(uri)
            return storage.Client().bucket(bucket).blob(key).download_as_bytes()
        if uri.startswith(("http://", "https://")):
            import httpx as _httpx
            return _httpx.get(uri, timeout=30, follow_redirects=True).content
        raise ValueError(f"Unsupported URI scheme for upload: {uri}")

    async def _load_named_artifact(name: str) -> tuple[bytes | None, str | None]:
        try:
            part = await tool_context.load_artifact(name)
        except Exception as e:
            _log.warning("load_artifact(%r) failed: %s", name, e)
            return None, None
        if not part or not getattr(part, "inline_data", None):
            return None, None
        cand_mime = part.inline_data.mime_type or ""
        if not cand_mime:
            ext = os.path.splitext(name)[1].lower()
            cand_mime = next(
                (m for m, e in _EXT_BY_MIME.items() if e == ext), ""
            )
        if not _mime_matches_kind(cand_mime, file_kind):
            return None, None
        return part.inline_data.data, cand_mime

    data: bytes | None = None
    mime: str | None = None
    debug: list[str] = []

    # Path 1: named artifact (Gemini Enterprise upload path)
    if filename:
        data, mime = await _load_named_artifact(filename)
        debug.append(f"named_artifact:{filename}={'hit' if data else 'miss'}")

    # Path 2: list artifacts and pick the latest matching one
    if data is None:
        try:
            names = await tool_context.list_artifacts() or []
            debug.append(f"artifacts:{names}")
            for name in reversed(names):
                ext = os.path.splitext(name)[1].lower()
                guessed_mime = next(
                    (m for m, e in _EXT_BY_MIME.items() if e == ext), None
                )
                if guessed_mime and _mime_matches_kind(guessed_mime, file_kind):
                    data, mime = await _load_named_artifact(name)
                    if data is not None:
                        if not filename:
                            filename = name
                        break
        except Exception as e:
            _log.warning("list_artifacts failed: %s", e)
            debug.append(f"list_artifacts_failed:{e}")

    # Path 3: scan Parts for inline_data / file_data
    def _scan_content(content):
        d = []
        if not content or not getattr(content, "parts", None):
            return None, None, d
        for part in content.parts:
            inline = getattr(part, "inline_data", None)
            if inline and inline.mime_type:
                d.append(f"inline_data:{inline.mime_type}")
                if _mime_matches_kind(inline.mime_type, file_kind):
                    return inline.data, inline.mime_type, d
            file_data = getattr(part, "file_data", None)
            if file_data and file_data.mime_type:
                d.append(f"file_data:{file_data.mime_type}")
                if _mime_matches_kind(file_data.mime_type, file_kind):
                    try:
                        return _fetch_uri(file_data.file_uri), file_data.mime_type, d
                    except Exception as e:
                        d.append(f"fetch_failed:{e}")
            if getattr(part, "text", None):
                d.append(f"text:{len(part.text)}c")
        return None, None, d

    if data is None:
        data, mime, dbg = _scan_content(getattr(inv, "user_content", None))
        debug.append(f"user_content={dbg}")
        if data is None:
            for ev in reversed(inv.session.events or []):
                _, _, dbg = _scan_content(ev.content)
                if dbg:
                    debug.append(
                        f"event[{getattr(ev, 'author', '?')}]={dbg}"
                    )
                data, mime, _ = _scan_content(ev.content)
                if data is not None:
                    break

    if data is None:
        _log.warning("save_uploaded_file(%s): no match. debug=%s", file_kind, debug)
        return {
            "error": (
                f"No uploaded {file_kind} file found. If you attached a file "
                "in chat, pass the filename via the `filename` argument."
            ),
            "debug": debug[:15],
        }

    _log.info(
        "save_uploaded_file(%s): matched name=%s mime=%s size=%d",
        file_kind, filename, mime, len(data),
    )

    ext = _EXT_BY_MIME.get(mime, ".bin")
    session_id = tool_context._invocation_context.session.id
    key = f"uploads/{session_id}/{filename_hint}_{int(time.time())}{ext}"

    bucket = storage.Client().bucket(_runtime_bucket())
    blob = bucket.blob(key)
    blob.upload_from_string(data, content_type=mime)

    uri = f"gs://{_runtime_bucket()}/{key}"
    out = {"gcs_uri": uri, "mime_type": mime, "size_bytes": len(data)}
    if file_kind == "image":
        # image_url is the gs:// URI. We don't round-trip a long signed
        # HTTPS URL through the model — Gemini's function-call serializer
        # silently truncates long string args (~half the signature was
        # cut, producing 403 sig-mismatch). MCP's download_image accepts
        # gs:// directly using its own SA creds, so no signing needed.
        out["image_url"] = uri
    return out


# ─── prepare_dataset ─────────────────────────────────────────────────────────


def _runtime_bucket() -> str:
    return os.environ["GCS_BUCKET_NAME"]


def _upload_excel_bytes(xlsx_bytes: bytes, key: str) -> str:
    bucket = storage.Client().bucket(_runtime_bucket())
    blob = bucket.blob(key)
    blob.upload_from_string(
        xlsx_bytes,
        content_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
    )
    return f"gs://{_runtime_bucket()}/{key}"


def _loads_lenient(s: str):
    """Parse a string that may be JSON or a Python repr (single-quoted dict).

    Adds two retries after Gemini's most common serialization mistakes:
      - bare numeric tokens with leading zeros (e.g. `product_id: 0123`),
        which both JSON and ast.literal_eval reject — wrap them as strings.
      - unescaped apostrophes inside single-quoted Python-repr strings
        (e.g. `'John's mug'`), which `ast.literal_eval` can't recover from
        — re-quote with double quotes after escaping internal doubles.
    """
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    try:
        return ast.literal_eval(s)
    except (ValueError, SyntaxError):
        pass
    # Retry 1: wrap unquoted leading-zero numbers. Only match in
    # value position (after `:`, `[`, `,`, or whitespace) followed by
    # a delimiter, to avoid touching strings that already contain "0123".
    fixed = re.sub(
        r'(?<=[:\[,\s])(0\d+)(?=[,}\]\s])',
        r'"\1"',
        s,
    )
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass
    try:
        return ast.literal_eval(fixed)
    except (ValueError, SyntaxError) as e:
        raise ValueError(
            f"Could not parse products payload ({type(e).__name__}: {e}). "
            "Pass `products` as a JSON array of objects with string-quoted "
            "product_id values."
        ) from e


def _normalize_products(products) -> list[dict]:
    """Coerce Gemini's varied function-call serializations into list[dict].

    Gemini sometimes passes `products` as a JSON string for the whole list,
    or as a list of JSON-stringified dicts, instead of a true list[dict].
    Falls back to `ast.literal_eval` if the string isn't valid JSON (e.g.
    Python-style single quotes).
    """
    if isinstance(products, str):
        products = _loads_lenient(products)
    return [_loads_lenient(p) if isinstance(p, str) else dict(p) for p in products]


def _products_to_xlsx_bytes(products) -> bytes:
    products = _normalize_products(products)
    by_category: dict[str, list[dict]] = {}
    for p in products:
        category = p.pop("_category", None) or p.get("category", "uncategorized")
        by_category.setdefault(category, []).append(
            {k: v for k, v in p.items() if k != "category"}
        )
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for category, rows in by_category.items():
            pd.DataFrame(rows).to_excel(writer, sheet_name=category[:31], index=False)
    return buf.getvalue()


def prepare_dataset(
    tool_context: ToolContext,
    source_uri: Optional[str] = None,
    products: Optional[list[dict]] = None,
) -> dict:
    """Normalize any product-data input into an Excel uploaded to GCS.

    Returns {"excel_uri": "gs://..."} ready to pass to the MCP server's
    upload_dataset(excel_path=...) tool.

    Inputs (provide exactly one):
      - source_uri: gs:// or http(s):// URI to an existing .xlsx / .csv / .json
      - products: list of product dicts. Each dict needs at minimum
          product_id, product_name. Optional: country, language, image_url,
          company_name, _category (sheet name; default "uncategorized").
    """
    if (source_uri is None) == (products is None):
        return {"error": "Provide exactly one of source_uri or products."}

    session_id = tool_context.state.get("session_id") or str(uuid.uuid4())[:8]
    ts = int(time.time())
    out_key = f"uploads/{session_id}/{ts}.xlsx"

    if products is not None:
        try:
            xlsx_bytes = _products_to_xlsx_bytes(products)
        except (ValueError, SyntaxError) as e:
            return {"error": str(e)}
        return {
            "excel_uri": _upload_excel_bytes(xlsx_bytes, out_key),
            "rows": len(products),
        }

    # source_uri path
    if source_uri.endswith(".xlsx") and source_uri.startswith("gs://"):
        return {"excel_uri": source_uri, "passthrough": True}

    # download into pandas
    if source_uri.startswith("gs://"):
        bucket, key = _parse_gs(source_uri)
        raw = storage.Client().bucket(bucket).blob(key).download_as_bytes()
    elif source_uri.startswith(("http://", "https://")):
        import httpx as _httpx

        raw = _httpx.get(source_uri, timeout=30, follow_redirects=True).content
    else:
        return {"error": f"Unsupported source_uri scheme: {source_uri}"}

    if source_uri.endswith(".xlsx"):
        return {"excel_uri": _upload_excel_bytes(raw, out_key)}
    if source_uri.endswith(".csv"):
        df = pd.read_csv(io.BytesIO(raw))
    elif source_uri.endswith(".json"):
        df = pd.read_json(io.BytesIO(raw))
    else:
        return {"error": f"Unsupported file type: {source_uri}"}

    rows = df.to_dict(orient="records")
    return {
        "excel_uri": _upload_excel_bytes(_products_to_xlsx_bytes(rows), out_key),
        "rows": len(rows),
    }
