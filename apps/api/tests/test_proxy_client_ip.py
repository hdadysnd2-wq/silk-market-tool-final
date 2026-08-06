"""Regression locks for proxy-aware client-IP resolution (audit blocker #8).

The per-IP auth throttle keyed on request.client.host. Behind the deployment
proxy that host is the SAME for every user, so 20 junk POSTs in 5 minutes 429'd
every legitimate login platform-wide (an unauthenticated login-lockout DoS).
_client_ip now reads the real client from X-Forwarded-For when trusted proxies
are configured, counting hops from the right so injected left-hand entries can't
spoof it.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.api.auth import _client_ip
from app.config import Settings


def _req(client_host: str, xff: str | None = None):
    headers = {}
    if xff is not None:
        headers["x-forwarded-for"] = xff
    return SimpleNamespace(
        client=SimpleNamespace(host=client_host),
        headers=headers,
    )


def test_uses_peer_when_no_trusted_proxy(monkeypatch):
    monkeypatch.setattr("app.config.get_settings", lambda: Settings(trusted_proxy_count=0))
    # Even with an XFF header, count=0 trusts only the direct peer.
    assert _client_ip(_req("10.0.0.1", xff="1.2.3.4")) == "10.0.0.1"


def test_reads_real_client_from_xff_behind_one_proxy(monkeypatch):
    monkeypatch.setattr("app.config.get_settings", lambda: Settings(trusted_proxy_count=1))
    # Railway edge appends the client's real IP; one hop → rightmost entry.
    assert _client_ip(_req("172.16.0.9", xff="203.0.113.7")) == "203.0.113.7"


def test_distinct_clients_get_distinct_ips(monkeypatch):
    """The core fix: two users behind the same proxy resolve to different IPs."""
    monkeypatch.setattr("app.config.get_settings", lambda: Settings(trusted_proxy_count=1))
    proxy = "172.16.0.9"  # identical direct peer for both
    a = _client_ip(_req(proxy, xff="203.0.113.7"))
    b = _client_ip(_req(proxy, xff="198.51.100.42"))
    assert a != b
    assert (a, b) == ("203.0.113.7", "198.51.100.42")


def test_spoofed_left_entries_are_ignored(monkeypatch):
    monkeypatch.setattr("app.config.get_settings", lambda: Settings(trusted_proxy_count=1))
    # Attacker prepends a fake IP; the proxy appends the real one → we pick right.
    assert _client_ip(_req("172.16.0.9", xff="9.9.9.9, 203.0.113.7")) == "203.0.113.7"


def test_falls_back_to_peer_when_xff_missing(monkeypatch):
    monkeypatch.setattr("app.config.get_settings", lambda: Settings(trusted_proxy_count=1))
    assert _client_ip(_req("172.16.0.9", xff=None)) == "172.16.0.9"


def test_login_throttle_isolates_clients_behind_proxy(client, db, monkeypatch):
    """End-to-end: one abusive client 429s itself, not everyone else."""
    from app.services import rate_limit

    monkeypatch.setattr("app.config.get_settings", lambda: Settings(trusted_proxy_count=1))
    rate_limit.reset()

    abuser = {"X-Forwarded-For": "203.0.113.7"}
    victim = {"X-Forwarded-For": "198.51.100.42"}

    # Abuse: 21 logins from ONE IP against many distinct accounts, so only the
    # per-IP bucket (limit 20) fills — not the per-account bucket (limit 8).
    statuses = [
        client.post(
            "/api/v1/auth/login",
            json={"email": f"abuse{i}@example.com", "password": "wrong-password"},
            headers=abuser,
        ).status_code
        for i in range(21)
    ]
    assert 429 in statuses  # the abusing IP eventually gets throttled

    # A different client (distinct XFF), fresh account, is NOT locked out.
    victim_status = client.post(
        "/api/v1/auth/login",
        json={"email": "victim@example.com", "password": "wrong-password"},
        headers=victim,
    ).status_code
    assert victim_status != 429
