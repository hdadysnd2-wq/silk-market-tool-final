"""Unauthenticated public endpoints — the one-click unsubscribe link.

Unsubscribing is a state change, so it happens on ``POST`` only (RFC 8058
one-click). ``GET`` never mutates: it renders a confirmation page with a button
that POSTs. This stops link prefetchers and corporate mail-security scanners —
which GET every URL in a message — from silently suppressing engaged recipients.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from app.api.deps import DbDep
from app.models import Contact, Email, SuppressionReason
from app.services import suppression

router = APIRouter(tags=["public"])

_CONFIRM_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Unsubscribed</title></head>
<body style="font-family:sans-serif;max-width:32rem;margin:4rem auto;text-align:center">
<h1>You have been unsubscribed</h1>
<p>You will not receive any further emails from this sender or any other campaign
on this platform.</p></body></html>"""


# A GET renders this page instead of unsubscribing. The visitor confirms with a
# button that POSTs to the same URL — the only path that mutates state. The form
# deliberately has no ``action`` attribute (it submits to the current URL), so the
# attacker-controlled token is never interpolated into the response HTML.
_CONFIRM_FORM_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Unsubscribe</title></head>
<body style="font-family:sans-serif;max-width:32rem;margin:4rem auto;text-align:center">
<h1>Unsubscribe</h1>
<p>Click the button below to stop receiving all emails from this sender.</p>
<form method="post">
<button type="submit"
style="font-size:1rem;padding:0.6rem 1.4rem;cursor:pointer">Unsubscribe me</button>
</form></body></html>"""


def _apply_unsubscribe(token: str, db: DbDep) -> None:
    email = db.scalar(select(Email).where(Email.unsubscribe_token == token))
    if email is None:
        return
    contact = db.get(Contact, email.contact_id)
    if contact is None:
        return
    suppression.suppress(
        db,
        email=contact.email,
        reason=SuppressionReason.unsubscribe,
        source_email_id=email.id,
        actor_label="recipient",
    )
    db.commit()


@router.get("/u/{token}", response_class=HTMLResponse)
def unsubscribe_form(token: str) -> HTMLResponse:
    """Render the confirmation page. Never mutates — safe for prefetch/scanners."""
    return HTMLResponse(content=_CONFIRM_FORM_HTML)


@router.post("/u/{token}", response_class=HTMLResponse)
def unsubscribe(token: str, db: DbDep) -> HTMLResponse:
    """Honor an unsubscribe. Global by design — suppresses across all campaigns.

    Handles both the RFC 8058 one-click POST (mail clients post here directly)
    and the confirmation-form button.
    """
    _apply_unsubscribe(token, db)
    # Always return the same confirmation so the token cannot be probed.
    return HTMLResponse(content=_CONFIRM_HTML)
