"""CAN-SPAM basics (I8): every outbound email footer must carry a **physical
postal address**, the sender's identity, and a working unsubscribe link.

This suite pins the physical-postal-address requirement specifically — a body
that names the company but omits its physical address is still non-compliant,
so ``ensure_compliance_footer`` keys its identity guard on the address line.
"""

from __future__ import annotations

from app.services.email_drafting import ensure_compliance_footer


def test_can_spam_footer_includes_physical_postal_address(db, factory):
    unsub = "https://silk.example/u/tok123"
    out = ensure_compliance_footer("We export premium Saudi dates.", factory, "en", unsub)

    # The physical postal address is present (CAN-SPAM §5 / PDPL identity).
    assert factory.postal_address == "Jeddah, Saudi Arabia"
    assert factory.postal_address in out
    # Sender identity + a working unsubscribe link accompany it.
    assert factory.name_en in out
    assert unsub in out


def test_can_spam_body_naming_company_without_address_still_gets_address(db, factory):
    # Names the company but omits the physical address — still non-compliant, so
    # the guard must append the identity block carrying the address.
    body = f"Regards, {factory.name_en}."
    out = ensure_compliance_footer(body, factory, "en", "https://silk.example/u/tok")

    assert factory.postal_address in out
