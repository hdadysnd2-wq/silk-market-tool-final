"""اختبارات الموجة ٧ — تصليب أمني P0 (النطاق المعتمد من المالك).

يقفل الأربعة:
1. C-1: مصادقة على كل نقاط القراءة (/analyses, /analyses/{id}, /brief, /report.docx).
2. L-1: مقارنة المفتاح ثابتة الزمن (hmac.compare_digest) — مفتاح خاطئ = 401.
3. M-2: السقف المدفوع يفشل مغلقاً عند خطأ قاعدة العدّاد (يرفض لا يسمح).
4. M-1: تحديد معدّل بسيط بالذاكرة — التجاوز = 429؛ ووضع التطوير بلا انحدار.
Run:  python3 -m pytest tests/ -q
"""
import contextlib
import os
import sys
import tempfile

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
    importlib.reload(api)            # التقط قيم البيئة الحالية عند البناء
    return TestClient(api.create_app())


def _store_one(db_path):
    """خزّن تحليلاً بسيطاً واعد معرّفه — persist a minimal analysis (JSON-safe)."""
    import silk_storage as storage
    result = {"product": "تمور", "hs_code": "080410", "year": 2023,
              "preliminary": True, "classified": True,
              "markets": [{"country": "الإمارات", "iso3": "ARE",
                           "total_score": 0.7, "confidence": 0.7,
                           "components": {}}]}
    return storage.save_analysis(result, db_path)


def test_c1_read_endpoints_require_key_when_auth_on():
    # C-1: مع ضبط SILK_API_KEY، كل نقاط القراءة ترفض بلا مفتاح (401)،
    # وتُرجع البيانات بمفتاح صحيح — لا تعداد مجهول للتحليلات المخزّنة.
    import pytest
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    db = os.path.join(tempfile.mkdtemp(), "silk.db")
    with _env(SILK_API_KEY="prod-secret", SILK_DB=db, SILK_RATE_LIMIT="1000"):
        aid = _store_one(db)
        client = _client()
        for path in ("/analyses", f"/analyses/{aid}",
                     f"/analyses/{aid}/brief", f"/analyses/{aid}/report.docx"):
            assert client.get(path).status_code == 401, path          # بلا مفتاح
            # L-1: مفتاح خاطئ يُرفض أيضاً (المقارنة ثابتة الزمن).
            assert client.get(
                path, headers={"X-API-Key": "wrong"}).status_code == 401, path
        h = {"X-API-Key": "prod-secret"}
        assert client.get("/analyses", headers=h).status_code == 200
        assert client.get(f"/analyses/{aid}", headers=h).status_code == 200
        assert client.get(f"/analyses/{aid}/brief", headers=h).status_code == 200
        assert client.get(
            f"/analyses/{aid}/report.docx", headers=h).status_code in (200, 501)


def test_c1_read_endpoints_open_in_dev_mode_no_regression():
    # بلا SILK_API_KEY (تطوير) => القراءة مفتوحة كالسابق — لا انحدار.
    import pytest
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    db = os.path.join(tempfile.mkdtemp(), "silk.db")
    with _env(SILK_API_KEY=None, SILK_DB=db, SILK_RATE_LIMIT="1000"):
        client = _client()
        assert client.get("/analyses").status_code == 200        # لا 401
        assert client.get("/analyses/999999").status_code == 404  # مفقود لا 401


def test_m1_rate_limit_returns_429_on_excess():
    # M-1: بسقف معدّل منخفض، الطلبات فوق الحدّ تُرفض 429 (ووضع التطوير مفتوح).
    import pytest
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    db = os.path.join(tempfile.mkdtemp(), "silk.db")
    with _env(SILK_API_KEY=None, SILK_DB=db,
              SILK_RATE_LIMIT="3", SILK_RATE_WINDOW="60"):
        client = _client()
        # ثبّت ساعة api أثناء الطلبات: النافذة الثابتة (now//60) قد تنقلب لو صادف
        # الاختبار حدود الدقيقة فيتصفّر العدّاد ويرجع 200 بدل 429 (flake حقيقي وقع
        # في CI). Freeze api's clock so the fixed window cannot roll mid-test.
        import types
        from unittest import mock
        import api as api_mod
        with mock.patch.object(api_mod, "time",
                               types.SimpleNamespace(time=lambda: 1_000_000.0)):
            codes = [client.get("/analyses").status_code for _ in range(5)]
        assert codes[:3] == [200, 200, 200]     # ضمن الحدّ
        assert codes[3] == 429 and codes[4] == 429   # التجاوز يُرفض


def test_m1_rate_limit_disabled_when_zero():
    # SILK_RATE_LIMIT=0 يعطّل الحدّ — لا 429 مهما تكرّر (وضع داخلي بلا حدّ).
    import pytest
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    db = os.path.join(tempfile.mkdtemp(), "silk.db")
    with _env(SILK_API_KEY=None, SILK_DB=db, SILK_RATE_LIMIT="0"):
        client = _client()
        assert all(client.get("/analyses").status_code == 200
                   for _ in range(6))


def test_m2_paid_cap_fails_closed_on_db_error_unit():
    # M-2: خطأ قاعدة العدّاد => try_reserve_paid_calls يرفض (False) لا يسمح.
    import silk_usage
    bad = tempfile.mkdtemp()          # مجلد بدل ملف => sqlite.connect يفشل
    assert silk_usage.try_reserve_paid_calls(1, bad) is False
    # ومسار سليم لا يتأثر (لا انحدار على السعة الطبيعية).
    good = os.path.join(tempfile.mkdtemp(), "usage.db")
    with _env(SILK_PAID_DAILY_CAP=None):
        assert silk_usage.try_reserve_paid_calls(1, good) is True


def test_m2_paid_cap_fails_closed_end_to_end_429():
    # M-2 عبر الـ API: عدّاد معطوب => /deepen بطبقة مدفوعة يُرفض 429 قبل أي وكيل.
    import pytest
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    bad_usage = tempfile.mkdtemp()    # مجلد => خطأ قاعدة العدّاد
    db = os.path.join(tempfile.mkdtemp(), "silk.db")
    with _env(SILK_API_KEY=None, VOLZA_API_KEY=None, EXPLEE_API_KEY=None,
              LOCALPRICE_API_KEY=None, ANTHROPIC_API_KEY=None,
              SILK_USAGE_DB=bad_usage, SILK_DB=db, SILK_RATE_LIMIT="1000"):
        client = _client()
        r = client.post("/deepen", json={"product": "تمور",
                                         "with_volza": True})
        assert r.status_code == 429            # يرفض المدفوع لا يسمح به
