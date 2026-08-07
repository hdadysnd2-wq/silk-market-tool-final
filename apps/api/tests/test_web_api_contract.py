"""Frontend-calls-vs-OpenAPI contract check (audit 2026-08-07 suggestion).

Extracts every ``api.get/post/put/del/blob(...)`` and ``useApi(...)`` path
literal from apps/web/src and asserts each one maps to a real FastAPI route with
the right method. This is the automated guard for the ``/u`` regression class
(a web call to an endpoint that doesn't exist) and for UI-orphan drift — it runs
in the existing API lane, where the app is importable.

Path params are matched structurally: the web's ``/products/{id}/buyers`` must
match the API's ``/products/{product_id}/buyers`` (same segment count, any
``{...}`` matches any ``{...}``). Query strings and non-static (fully computed)
paths are skipped and counted, so the check never blocks on something it cannot
statically resolve — it only fails on a concrete web call with no backing route.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.main import create_app

WEB_SRC = Path(__file__).resolve().parents[3] / "apps" / "web" / "src"
API_PREFIX = "/api/v1"

# api.<method>("path"...) / api.<method>(`path`...) / useApi("path") / useApi(`path`)
_CALL = re.compile(
    r"""(?:api\.(?P<m>get|post|put|del|blob)|(?P<useapi>useApi))"""
    r"""\s*(?:<[^>(]*>)?\s*\(\s*(?P<q>["`])(?P<path>/[^"`]+)(?P=q)""",
    re.VERBOSE,
)
_METHOD = {"get": "get", "post": "post", "put": "put", "del": "delete", "blob": "get"}


def _canonical(path: str) -> str:
    """Strip the query string and replace every {param}/`${expr}` with {}."""
    path = path.split("?", 1)[0]
    path = re.sub(r"\$\{[^}]*\}", "{}", path)  # template interpolation → {}
    path = re.sub(r"\{[^}]*\}", "{}", path)  # named path params → {}
    return path.rstrip("/") or "/"


def _openapi_routes() -> set[tuple[str, str]]:
    spec = create_app().openapi()
    routes: set[tuple[str, str]] = set()
    for raw_path, methods in spec["paths"].items():
        if not raw_path.startswith(API_PREFIX):
            continue
        rel = raw_path[len(API_PREFIX) :] or "/"
        for method in methods:
            routes.add((method.lower(), _canonical(rel)))
    return routes


def _web_calls() -> list[tuple[str, str, str]]:
    """(method, canonical_path, raw_path) for every extractable web call."""
    calls: list[tuple[str, str, str]] = []
    for tsx in WEB_SRC.rglob("*.tsx"):
        for m in _CALL.finditer(tsx.read_text()):
            method = "get" if m.group("useapi") else _METHOD[m.group("m")]
            raw = m.group("path")
            calls.append((method, _canonical(raw), raw))
    for ts in WEB_SRC.rglob("*.ts"):
        for m in _CALL.finditer(ts.read_text()):
            method = "get" if m.group("useapi") else _METHOD[m.group("m")]
            raw = m.group("path")
            calls.append((method, _canonical(raw), raw))
    return calls


def test_every_web_api_call_has_a_backing_route():
    routes = _openapi_routes()
    calls = _web_calls()
    assert calls, "no web API calls were extracted — the regex likely broke"

    missing = [
        (method, raw) for method, canon, raw in calls if (method, canon) not in routes
    ]
    assert not missing, (
        "web calls with no backing FastAPI route (the /u regression class):\n"
        + "\n".join(f"  {method.upper()} {raw}" for method, raw in sorted(missing))
    )
