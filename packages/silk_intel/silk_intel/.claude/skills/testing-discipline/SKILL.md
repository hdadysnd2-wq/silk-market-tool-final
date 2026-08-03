---
name: testing-discipline
description: The hermetic test system of the Silk repo — copy-paste idioms for network blocking, env isolation, AST architecture tests, and the no-fabrication assertion style. Load before writing or modifying anything under tests/, or before adding any new data path (which must ship its hermetic test the same day).
---

# Testing discipline (hermetic suite)

The tests are the ONLY thing that keeps the accuracy guarantees intact. Every rule
below traces to a real past contamination incident. Follow mechanically.

## 1. Ground rules

1. The suite is hermetic: ~5s, zero network, zero API keys. Run: `python3 -m pytest tests/ -q`.
2. CI (`.github/workflows/ci.yml`) runs exactly `python -m pytest tests/ -q` on Python 3.11
   after `pip install -r requirements.txt pytest httpx`. There is no pytest.ini, no markers,
   no ordering plugins — never introduce them.
3. Every test file starts with the path shim (conftest.py:12, test_smoke.py:10):
   ```python
   import os, sys
   sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
   ```
4. Optional deps are gated, never assumed:
   ```python
   import pytest
   pytest.importorskip("fastapi")
   pytest.importorskip("httpx")   # TestClient needs it; test-only dep
   pytest.importorskip("docx")    # for report tests
   ```
5. New tests import the canonical guard from conftest: `from conftest import block_network`
   (conftest.py:15-30). Older files carry local `_block_network` copies — historical, do not
   copy them into new files.
6. Suite size at last count: 715 test functions (matches commit #71's "715 passed").
   Every wave ADDS tests; the existing suite stays green.

## 2. The two network-blocking mechanisms (the #1 trap)

| Test type | Mechanism | Why |
|---|---|---|
| Library-level (call engine/agents/store directly) | `with block_network():` — monkeypatches `socket.socket` (conftest.py:15-30) | Kills ALL outbound sockets, proving the no-fabrication path |
| FastAPI `TestClient` tests | `patch("requests.sessions.Session.request", side_effect=OSError(...))` | Global socket blocking BREAKS TestClient's internal transport (asyncio socketpair) — the test fails on infrastructure, not on your code |

The exact failure mode is documented inline at tests/test_smoke.py:120-123:
> لا نستخدم `_block_network` هنا: تعطّل `socket.socket` عالمياً يكسر نقل TestClient
> الداخلي (asyncio socketpair)؛ بدلاً منها نعطّل requests.get فقط — نفس الأثر الحتمي.

Canonical TestClient idiom (test_smoke.py:109-135):
```python
from unittest.mock import patch
from fastapi.testclient import TestClient
import api

client = TestClient(api.app)
with patch("requests.sessions.Session.request",
           side_effect=OSError("network disabled for offline test")):
    r = client.post("/deepen", json={"product": "تمور", "year": 2022})
```

Belt-and-suspenders TRIPLE patch — required whenever Claude/Anthropic calls must be
blocked or spied (the anthropic path uses `requests.post`, data layers use `requests.get`,
sessions use `Session.request`). Copy from tests/test_project_review_fixes.py:104-117:
```python
def spy_post(*a, **k):
    posts.append(a[0] if a else k.get("url"))
    raise OSError("network disabled for offline test")

with mock.patch("requests.get", side_effect=OSError("network disabled for offline test")), \
     mock.patch("requests.sessions.Session.request",
                side_effect=OSError("network disabled for offline test")), \
     mock.patch("requests.post", side_effect=spy_post):
    r = TestClient(api.app).post("/analyze", json={"product": "تمور"})
assert not any("anthropic" in str(u) for u in posts)   # zero Claude calls
```
Never mix: do NOT open `block_network()` around a TestClient call, and do not rely on
requests-patching for library-level tests (a stray `urllib`/`socket` path would slip through).

## 3. The "hermetic" word trap

`silk_reports._assert_production_clean` (silk_reports.py:30-45) REJECTS any report view
whose serialized JSON contains one of `_HERMETIC_MARKERS` (silk_reports.py:26-27):
`"MagicMock"`, `"example.org"`, `"hermetic"`, `"demo double"`, `"بدائل موسومة"`.

Consequence: conftest's `block_network` raises
`OSError("network disabled for offline test")` — deliberately NOT the word "hermetic"
(the Arabic comment at conftest.py:21-23 explains this). The OSError text flows into
DataPoint notes, notes flow into the view, and the view feeds `render_docx`/`render_brief`/
`render_markdown` (each calls `_assert_production_clean` — silk_reports.py:581, 1230, 1555).
An injected error message containing "hermetic" poisons every derived-report test.

Rules for new test doubles:
1. Error strings in `side_effect=OSError(...)` and fakes must avoid ALL five markers.
   Use `"network disabled for offline test"` or `"net blocked"`.
2. Never name fake domains `example.org` — use `example.invalid` (as test_smoke.py:149 does).
3. Older files (test_smoke.py:23, test_project_review_fixes.py:69-71) still say "hermetic" —
   safe only because those specific tests never render reports. Do NOT copy that wording
   into any test that touches `silk_reports` or `view`.
4. A test that legitimately wants a marked demo report sets `SILK_HERMETIC=1` or
   `view["test_run"]=True` (the guard's declared bypass, silk_reports.py:36-37) — the
   report then carries the visible "TEST RUN" banner instead.

## 4. conftest autouse isolation (each item = a real contamination incident)

`_isolated_fact_store` (conftest.py:53-73) runs for EVERY test. What it does and why:

| Isolation | Incident it fixed |
|---|---|
| `SILK_STORE_DB` → fresh tempdir per test | A transient M2 write warmed the default store; real facts leaked between tests (caught via `test_engine_localprice_layer_offline`) |
| `SILK_HTTP_MIN_GAP_MS=0` | 250ms inter-call spacing × hundreds of failing offline calls would slow the suite pointlessly |
| `SILK_TRACE_DIR` → tempdir | Real `/research` TestClient tests were writing `data/traces/*.jsonl` to disk |
| `silk_context._data_counter.set(None)` | pytest runs all tests on one thread; a leftover counter with high numbers falsely tripped the global LLM cap in `silk_llm_runtime._run_loop` in an unrelated later test (wave 6 regression, actually observed) |

Do not weaken or bypass this fixture. If a test needs a specific store path, it overrides
`SILK_STORE_DB` itself — the fixture's monkeypatch is restored per test.

`docx_all_text(path)` (conftest.py:33-45) is the ONLY correct way to read a generated
Word report: it reads paragraphs AND table cells. `doc.paragraphs` alone misses content
that moved into real tables — tests using it falsely passed/failed when sections became
tables.

## 5. Env vars, module reload, and time freezing

Canonical `_env(**vals)` context manager — None means ensure-unset; restore is guaranteed.
Copy verbatim from tests/test_project_review_fixes.py:19-34:
```python
@contextlib.contextmanager
def _env(**vals):
    """اضبط متغيرات بيئة مع استرجاع مضمون — set env vars, guaranteed restore."""
    old = {k: os.environ.get(k) for k in vals}
    try:
        for k, v in vals.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
```

Module-level constants read at import time (e.g. `silk_ai_judge._TIMEOUT` from
`SILK_AI_TIMEOUT_S`, api.py's `_rl_max`) need `importlib.reload` inside try/finally —
copy from tests/test_wave_p1_ai_timeout_and_failure_reasons.py:59-69:
```python
import silk_ai_judge as aj
try:
    with _env(SILK_AI_TIMEOUT_S="120"):
        importlib.reload(aj)
        assert aj._TIMEOUT == 120.0
finally:
    importlib.reload(aj)   # restore defaults for the rest of the suite
```
The `_client()` helper pattern (test_wave0_security.py:34+, test_m0_hotfixes.py:39-43)
does `importlib.reload(api)` then `TestClient(api.create_app())` so the app captures the
current env values at build time.

Rate-limit tests must freeze time — the fixed window flips mid-test otherwise
(the wave-7 lesson). Copy from tests/test_m0_hotfixes.py:86-93:
```python
import api as api_mod
with mock.patch.object(api_mod, "time",
                       types.SimpleNamespace(time=lambda: 2_000_000.0)):
    codes = [client.patch(...).status_code for _ in range(5)]
```

## 6. AST / source architecture tests

Architectural guarantees ("this module imports no network library") are enforced
structurally. The copyable idiom (tests/test_wave5a_discovery.py:100-115):
```python
import ast, inspect
import silk_discovery

tree = ast.parse(inspect.getsource(silk_discovery))
imported = {n.names[0].name.split(".")[0] for n in ast.walk(tree)
            if isinstance(n, ast.Import)}
imported |= {(n.module or "").split(".")[0] for n in ast.walk(tree)
             if isinstance(n, ast.ImportFrom)}
assert imported.isdisjoint({"requests", "urllib", "http", "httpx", "socket"})
allowed = {"silk_data_layer", "silk_trends_agent", "silk_hs_resolver",
           "functools", "logging", "__future__"}
assert imported <= allowed, imported            # zero new sources
```
Variants:
- correlation.py version also forbids `anthropic` and `silk_ai_judge`
  (tests/test_wave4_correlation.py:161-177).
- Source-inspection variant: `inspect.getsource(fn)` + substring asserts for
  function-level guarantees.
- ALWAYS pair structural with behavioral: after the AST assert, run the module under
  `block_network()` and assert the full output shape (see test_wave4_correlation.py:175-177
  and test_wave5a_discovery.py:140-151). Structure without behavior proves nothing.

## 7. The founding assertion style + naming

Offline/keyless/bad-payload ⇒ THREE asserts together, never fewer:
```python
assert dp.value is None          # never 0, never a default
assert dp.confidence == 0.0
assert "تعذّر" in dp.note        # the reason is DECLARED (match the actual note text)
```
Never assert `== 0` for a missing value — a fabricated zero is exactly the bug class
this suite exists to catch. Partial data lowers confidence and declares the drop:
see tests/test_smoke.py:330-353 (`"بلا قيمة رقمية" in dp.note`, `confidence < 0.9`)
vs the all-missing declared gap at test_smoke.py:356-372 (`"بلا قيم رقمية"`).

Naming conventions (keep them):
- `tests/test_wave{N}_*.py`, `tests/test_stage{N}_*.py`, `tests/test_p{N}_*.py`,
  `tests/test_m{N}_*.py` — one file per work wave.
- Acceptance criteria are LITERAL named tests `test_acceptance_{n}_{slug}` mapping the
  vision sections: §1.7 → tests/test_wave4_correlation.py, §11.5 →
  tests/test_wave5a_discovery.py, §12.7 → tests/test_wave5b_compliance.py.
  When touching those areas, keep the mapping intact and update the same-named tests.
- Docstrings are Arabic-first and tell the incident story (why the test exists),
  with an English mirror where useful. Match that style.
- A new data path (agent, source wrapper, enrichment layer) ships its hermetic test
  THE SAME DAY, in the same PR — this is enforced by review, not optional.

## 8. Pre-commit checklist

1. `python3 -m pytest tests/ -q` — full suite green (no test selection tricks).
2. New offline paths assert `None` + `0.0` + declared note (never zeros).
3. No `_HERMETIC_MARKERS` word appears in any injected error string reaching a view.
4. TestClient tests patch requests; library tests use `block_network` — never both.
5. If a module-level env constant was touched, reload idiom with finally-restore is used.
