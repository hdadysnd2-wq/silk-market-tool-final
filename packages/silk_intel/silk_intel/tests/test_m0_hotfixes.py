"""اختبارات M0 — الإصلاحات الساخنة (خطة إعادة البناء §12).

يقفل الأربعة:
1. ثغرة PATCH /analyses/{id}/outcome: صارت خلف المصادقة وتحديد المعدّل
   (كانت الوحيدة المكشوفة بلا حارس — ANALYSIS.md §7-1).
2. GET /index: معامل limit مُقيَّد بسقف أعلى (لا استنزاف بالتعداد).
3. GET /sources: أعلام key_present لا تُكشف لمجهول عندما تكون المصادقة
   مفعّلة (تسريب إعدادات الخادم — ANALYSIS.md §7-5).
4. وجود conftest.block_network القانوني (بديل النسخ المكرّرة).
Run:  python3 -m pytest tests/ -q
"""
import contextlib
import os
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@contextlib.contextmanager
def _env(**kw):
    saved = {k: os.environ.get(k) for k in kw}
    try:
        for k, v in kw.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = str(v)
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _client():
    from fastapi.testclient import TestClient
    import importlib
    import api
    importlib.reload(api)
    return TestClient(api.create_app())


def _store_one(db_path):
    import silk_storage as storage
    result = {"product": "تمور", "hs_code": "080410", "year": 2023,
              "preliminary": True, "classified": True, "markets": []}
    with _env(SILK_DB=db_path):
        storage.init_db(db_path)
        return storage.save_analysis(result, path=db_path)


def test_outcome_patch_requires_key_when_auth_enabled():
    # الثغرة المُصلَحة: بلا ترويسة أو بمفتاح خاطئ = 401؛ بالمفتاح الصحيح = 200.
    import pytest
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    db = os.path.join(tempfile.mkdtemp(), "silk.db")
    aid = _store_one(db)
    with _env(SILK_API_KEY="sekret", SILK_DB=db, SILK_RATE_LIMIT="1000"):
        client = _client()
        r = client.patch(f"/analyses/{aid}/outcome", json={"outcome": "launched"})
        assert r.status_code == 401                     # بلا ترويسة
        r = client.patch(f"/analyses/{aid}/outcome", json={"outcome": "launched"},
                         headers={"X-API-Key": "wrong"})
        assert r.status_code == 401                     # مفتاح خاطئ
        r = client.patch(f"/analyses/{aid}/outcome", json={"outcome": "launched"},
                         headers={"X-API-Key": "sekret"})
        assert r.status_code == 200 and r.json()["recorded"] is True


def test_outcome_patch_is_rate_limited():
    # PATCH يخضع لتحديد المعدّل مثل بقية النقاط (كان بلا حدّ إطلاقاً).
    import pytest
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from unittest import mock
    db = os.path.join(tempfile.mkdtemp(), "silk.db")
    aid = _store_one(db)
    with _env(SILK_API_KEY=None, SILK_DB=db,
              SILK_RATE_LIMIT="3", SILK_RATE_WINDOW="60"):
        client = _client()
        import api as api_mod
        # ثبّت الساعة كي لا تنقلب النافذة الثابتة منتصف الاختبار (نفس درس wave7).
        with mock.patch.object(api_mod, "time",
                               types.SimpleNamespace(time=lambda: 2_000_000.0)):
            codes = [client.patch(f"/analyses/{aid}/outcome",
                                  json={"outcome": "x"}).status_code
                     for _ in range(5)]
        assert codes[3] == 429 and codes[4] == 429


def test_index_limit_is_clamped():
    # limit ضخم أو سالب لا يُمرَّر كما هو — يُقصّ إلى [1..100].
    import pytest
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    with _env(SILK_API_KEY=None, SILK_RATE_LIMIT="0"):
        client = _client()
        r = client.get("/index", params={"q": "", "limit": 100000})
        assert r.status_code == 200 and len(r.json()) <= 100
        r = client.get("/index", params={"q": "", "limit": -5})
        assert r.status_code == 200 and len(r.json()) <= 100


def test_sources_hides_key_flags_from_anonymous_when_auth_enabled():
    # المصادقة مفعّلة: مجهول يرى الطبقات بلا أعلام key_present (لا تسريب إعدادات)؛
    # حامل المفتاح يراها. وضع التطوير (بلا SILK_API_KEY) بلا تغيير.
    import pytest
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    with _env(SILK_API_KEY="sekret", SEARCH_API_KEY="present-key",
              SILK_RATE_LIMIT="1000"):
        client = _client()
        anon = client.get("/sources").json()
        assert all("key_present" not in row for row in anon)   # لا كشف لمجهول
        assert all("name" in row and "type" in row for row in anon)  # القائمة تبقى
        authed = client.get("/sources", headers={"X-API-Key": "sekret"}).json()
        ws = [r for r in authed if r.get("key_env") == "SEARCH_API_KEY"][0]
        assert ws["key_present"] is True                        # المصرَّح يرى الحقيقة
    with _env(SILK_API_KEY=None, SILK_RATE_LIMIT="1000"):
        client = _client()
        dev = client.get("/sources").json()
        assert all("key_present" in row for row in dev)         # وضع التطوير كما كان


def test_conftest_block_network_is_canonical():
    # المُساعد القانوني موجود ويعمل (الاختبارات الجديدة تستورده حصراً).
    from conftest import block_network
    import socket
    with block_network():
        try:
            socket.socket()
            raised = False
        except OSError:
            raised = True
    assert raised
    socket.socket()  # restored
