"""Shared OAuth2 authorization-code helpers for the real mailbox providers.

Gmail and Microsoft speak the same OAuth2 dialect for the token endpoint, so the
POST + error mapping lives here once. Nothing in this module touches the DB.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from app.logging import get_logger
from app.providers.base import OAuthTokens, TokenRefreshError

log = get_logger(__name__)

#: OAuth error codes that mean the grant is gone for good — the user must
#: re-consent. Anything else is treated as a transient failure by the caller.
_REVOKED_ERRORS = {"invalid_grant", "invalid_token", "unauthorized_client"}


def exchange(
    *,
    token_url: str,
    client_id: str,
    client_secret: str,
    data: dict[str, str],
    timeout: float = 30.0,
) -> OAuthTokens:
    """POST to a token endpoint and normalise the response into ``OAuthTokens``.

    Raises ``TokenRefreshError`` for a revoked/expired grant (so the caller can
    trigger the reauth path) and ``httpx.HTTPError`` for transient failures.
    """
    payload = {"client_id": client_id, "client_secret": client_secret, **data}
    with httpx.Client(timeout=timeout) as client:
        response = client.post(
            token_url,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    if response.status_code >= 400:
        error = ""
        try:
            error = str(response.json().get("error", ""))
        except ValueError:
            error = response.text[:200]
        # Never log token values; only the OAuth error code.
        log.warning("oauth_token_endpoint_error", status=response.status_code, error=error)
        if error in _REVOKED_ERRORS:
            raise TokenRefreshError(f"grant revoked: {error}")
        response.raise_for_status()

    body = response.json()
    expires_in = body.get("expires_in")
    expires_at = datetime.now(UTC) + timedelta(seconds=int(expires_in)) if expires_in else None
    return OAuthTokens(
        access_token=body["access_token"],
        # Google omits refresh_token on refresh; callers keep the prior one.
        refresh_token=body.get("refresh_token"),
        expires_at=expires_at,
        scopes=body.get("scope"),
    )
