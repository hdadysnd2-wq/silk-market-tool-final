"""Authoritative deliverability DNS check (SPF / DKIM / DMARC).

Tenants must not be able to *assert* that their sending domain is authenticated —
the platform verifies it by resolving the domain's TXT records itself. This module
is the single place that resolution happens; the ``PUT /factory*`` schemas no
longer accept the flags, so the only way they flip to ``True`` is a real check
here (I8 / anti-spoofing).

``_resolve_txt`` is the network seam: tests monkeypatch it (or pass a ``resolver``)
so the suite stays hermetic and offline.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class DnsCheckResult:
    spf_ok: bool = False
    dkim_ok: bool = False
    dmarc_ok: bool = False
    # Human-readable, per-mechanism outcome (no secrets — TXT records are public).
    notes: dict[str, str] = field(default_factory=dict)


Resolver = Callable[[str], list[str]]


def _resolve_txt(name: str) -> list[str]:
    """Resolve TXT records for ``name`` into a list of decoded strings.

    Returns ``[]`` when the name has no TXT records or does not exist; other
    resolution failures propagate so the caller can note them. dnspython is
    imported lazily so the module still loads where it is absent (e.g. the
    pandas-guard lane) — real resolution requires the dependency.
    """
    import dns.resolver  # lazy: only needed for a live check
    from dns.exception import DNSException

    try:
        answers = dns.resolver.resolve(name, "TXT")
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return []
    except DNSException:
        raise
    # Each record is a sequence of byte strings; join and decode.
    return ["".join(b.decode("utf-8", "ignore") for b in rec.strings) for rec in answers]


def _safe(resolver: Resolver, name: str, notes: dict[str, str], key: str) -> list[str]:
    try:
        return resolver(name)
    except Exception as exc:  # noqa: BLE001 — record any resolution error as a note
        notes[key] = f"lookup failed: {type(exc).__name__}"
        return []


def check_deliverability(
    domain: str,
    *,
    dkim_selectors: tuple[str, ...] = ("default",),
    resolver: Resolver | None = None,
) -> DnsCheckResult:
    """Resolve SPF, DKIM, and DMARC for ``domain`` and report what passed."""
    # Resolve the default at call time (not as a bound default arg) so tests can
    # monkeypatch ``dns_check._resolve_txt`` to stay offline.
    if resolver is None:
        resolver = _resolve_txt
    result = DnsCheckResult()

    # SPF — a TXT record on the apex starting with "v=spf1".
    spf = _safe(resolver, domain, result.notes, "spf")
    if any(r.lower().startswith("v=spf1") for r in spf):
        result.spf_ok = True
        result.notes["spf"] = "SPF record found"
    else:
        result.notes.setdefault("spf", "no v=spf1 TXT record")

    # DMARC — a TXT record at _dmarc.<domain> starting with "v=DMARC1".
    dmarc = _safe(resolver, f"_dmarc.{domain}", result.notes, "dmarc")
    if any(r.lower().startswith("v=dmarc1") for r in dmarc):
        result.dmarc_ok = True
        result.notes["dmarc"] = "DMARC record found"
    else:
        result.notes.setdefault("dmarc", "no v=DMARC1 TXT record")

    # DKIM — a TXT record at <selector>._domainkey.<domain>; providers use
    # different selectors, so pass if any candidate resolves a DKIM key.
    for selector in dkim_selectors:
        records = _safe(resolver, f"{selector}._domainkey.{domain}", result.notes, "dkim")
        if any(("v=dkim1" in r.lower()) or ("p=" in r.lower()) for r in records):
            result.dkim_ok = True
            result.notes["dkim"] = f"DKIM record found (selector: {selector})"
            break
    else:
        result.notes.setdefault("dkim", "no DKIM record for any known selector")

    return result
