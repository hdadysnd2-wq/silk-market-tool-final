"""Log-safe rendering of provider HTTP errors.

Some vendors (Smartlead, ZeroBounce) authenticate with the API key as a URL
*query parameter*. httpx builds its exception messages from the full request
URL — query string included — so logging ``str(exc)`` on any non-2xx response
writes the cleartext key to the application logs (and, for the sending path,
into the persisted ``Email`` error state). Routine 401/429/5xx responses would
then leak a live paid credential to anyone with log-read access.

``safe_error`` collapses such a failure to a status code (or the exception type)
and never emits the URL. ``redact_secrets`` is a defense-in-depth scrub for any
secret-bearing query fragment that still reaches a log line by another path.
"""

from __future__ import annotations

import re

import httpx

#: Matches ``<name>=<value>`` for common credential query keys so the value can
#: be masked. Value stops at the next ``&``, whitespace, or quote.
_SECRET_QUERY_RE = re.compile(
    r"(?i)(api_key|apikey|access_key|secret|key|token|password)=([^&\s'\"]+)"
)


def redact_secrets(text: str) -> str:
    """Mask credential values in a query-string-bearing message."""
    return _SECRET_QUERY_RE.sub(r"\1=REDACTED", text)


def safe_error(exc: Exception) -> str:
    """A log-safe description of a provider request failure.

    For an HTTP status error, return just ``HTTP <code>`` — never the URL, which
    would carry a query-string API key. For any other error keep the exception
    type and a secret-scrubbed detail so the log stays useful without leaking.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        # exc.response is normally set, but guard against a hand-built error with
        # response=None — fall through to the type-only rendering rather than crash.
        status_code = getattr(exc.response, "status_code", None)
        if status_code is not None:
            return f"HTTP {status_code}"
        return type(exc).__name__
    detail = redact_secrets(str(exc)).strip()
    return f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__
