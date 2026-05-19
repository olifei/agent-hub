# ruff: noqa
"""ID-token auth for the deployed Ads Video MCP server (Cloud Run, IAM-only).

The MCP server is deployed with `--no-allow-unauthenticated`, so every request
needs `Authorization: Bearer <google-id-token>` whose audience is the Cloud Run
service URL. Tokens last ~1h and are minted per request to keep long-lived
agent sessions alive.

Two modes:
- **Production** (Agent Runtime / Cloud Run / GKE): the runtime SA itself has
  `roles/run.invoker` on the MCP service. `fetch_id_token` mints a token for
  that SA directly.
- **Local dev** (user ADC, e.g. cloudtop): `fetch_id_token` returns a token
  for the cloudtop shared SA, which doesn't have invoker. Set
  `MCP_IMPERSONATE_SA=<sa@project.iam.gserviceaccount.com>` to impersonate
  the production SA. Requires `roles/iam.serviceAccountTokenCreator` on
  that SA for the developer.
"""

from __future__ import annotations

import os

import httpx
from google.auth import default as google_auth_default
from google.auth import impersonated_credentials
from google.auth.transport.requests import Request
from google.oauth2.id_token import fetch_id_token


def _mint_id_token(audience: str) -> str:
    impersonate_sa = os.environ.get("MCP_IMPERSONATE_SA")
    if not impersonate_sa:
        return fetch_id_token(Request(), audience)

    source_creds, _ = google_auth_default()
    target_creds = impersonated_credentials.IDTokenCredentials(
        target_credentials=impersonated_credentials.Credentials(
            source_credentials=source_creds,
            target_principal=impersonate_sa,
            target_scopes=["https://www.googleapis.com/auth/cloud-platform"],
        ),
        target_audience=audience,
        include_email=True,
    )
    target_creds.refresh(Request())
    return target_creds.token


class IdTokenAuth(httpx.Auth):
    requires_request_body = False
    requires_response_body = False

    def __init__(self, audience: str) -> None:
        self._audience = audience

    def auth_flow(self, request):
        request.headers["Authorization"] = f"Bearer {_mint_id_token(self._audience)}"
        yield request


def make_authed_httpx_client_factory(audience: str):
    """Returns an httpx_client_factory that injects ID-token auth.

    Signature matches mcp.shared._httpx_utils.create_mcp_http_client:
        (headers, timeout, auth) -> httpx.AsyncClient
    """

    def factory(headers=None, timeout=None, auth=None):
        from mcp.shared._httpx_utils import create_mcp_http_client

        return create_mcp_http_client(
            headers=headers, timeout=timeout, auth=auth or IdTokenAuth(audience)
        )

    return factory
