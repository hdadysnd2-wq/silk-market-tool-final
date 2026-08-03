"""اختبارات الموجة ٢ (البنية) — hermetic wave-2 tests: /deepen + BaseAgent.

تغطي: الحصر البنيوي للمدفوع (يستحيل خارج /deepen حتى بمفتاح)، المسار العادي
فقد المدفوع نهائياً، حرّاس الموجة ٠ على /deepen، والفشل الصامت مستحيل بنيوياً.
Run:  python3 -m pytest tests/ -q
"""
import contextlib
import os
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# مرجع قانوني موحَّد (conftest.py) — راجع تعليق test_smoke.py لسبب توحيد
# النسخ المحلية المكرَّرة (تسريب اتصال مجمَّع عبر جلسة requests المشتركة).
from conftest import block_network as _block_network


@contextlib.contextmanager
def _env(**vals):
    """اضبط بيئة مؤقتة — set env vars, always restoring."""
    saved = {k: os.environ.get(k) for k in vals}
    try:
        for k, v in vals.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, old in saved.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old


def _client():
    import pytest
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    import api
    return TestClient(api.create_app())


def test_paid_agent_structurally_impossible_outside_deepen():
    # مفتاح مضبوط + خارج سياق /deepen => لا نداء شبكة إطلاقاً (الحارس بنيوي).
    from silk_volza_agent import VolzaAgent

    with _env(VOLZA_API_KEY="real-looking-key"):
        with _block_network():  # أي محاولة نداء سترمي — يجب ألا تُحاوَل أصلاً
            rep = VolzaAgent().run({"hs_code": "080410", "market": 784})
    assert rep.failed is True
    assert "outside /deepen" in rep.summary
    dp = rep.findings[0]
    assert dp.value is None and dp.confidence == 0.0
    assert "outside /deepen" in dp.note and "no call attempted" in dp.note


def test_paid_agent_executes_inside_deepen_context():
    # داخل السياق يصل التنفيذ الفعلي (_execute) — keyless => ملاحظة الاشتراك.
    import silk_context
    from silk_volza_agent import VolzaAgent

    with _env(VOLZA_API_KEY=None):
        with silk_context.deepen_context():
            rep = VolzaAgent().run({"hs_code": "080410", "market": 784})
    assert rep.failed is True
    assert "paid subscription" in rep.findings[0].note  # وصلنا منطق الوكيل نفسه


def test_deepen_context_is_scoped():
    # السياق ينتهي بانتهاء الكتلة — لا تسرّب عالمي.
    import silk_context

    assert silk_context.deepen_active() is False
    with silk_context.deepen_context():
        assert silk_context.deepen_active() is True
    assert silk_context.deepen_active() is False


def test_base_agent_exception_becomes_noted_report():
    # استثناء من _execute => تقرير فاشل بـ DataPoint موسوم — بنيوياً لا مراجعةً.
    from silk_agents import BaseAgent

    class BoomAgent(BaseAgent):
        SOURCE = "BoomSource"

        def __init__(self):
            super().__init__("BoomAgent")

        def _execute(self, task):
            raise RuntimeError("kaboom")

    rep = BoomAgent().run({})
    assert rep.failed is True
    dp = rep.findings[0]
    assert dp.value is None and dp.source == "BoomSource"
    assert "kaboom" in dp.note


def test_analyze_endpoint_cannot_activate_paid_layers():
    # الموجة ٢: /analyze يتجاهل الحقول المدفوعة بنيوياً — لا volza/localprice بالرد.
    from unittest.mock import patch

    client = _client()
    with patch("requests.sessions.Session.request",
               side_effect=OSError("network disabled for hermetic test")):
        r = client.post("/analyze", json={
            "product": "تمور", "year": 2022,
            "with_volza": True, "with_explee": True,
            "with_localprice": True, "own_price": 25.0, "with_ai": True,
        })
    assert r.status_code == 200
    row = r.json()["markets"][0]
    for key in ("volza", "explee", "localprice", "price_comparison"):
        assert key not in row          # الحقول المدفوعة لم تصل المحرّك أصلاً
    assert "report" not in r.json()    # ولا طبقة كلود


def test_deepen_endpoint_guards_auth_and_cap():
    # حارسا الموجة ٠ يعملان على /deepen: 401 بلا مفتاح، 429 فوق السقف.
    import tempfile

    usage_db = os.path.join(tempfile.mkdtemp(), "usage.db")
    with _env(SILK_API_KEY="deep-secret", SILK_PAID_DAILY_CAP="0",
              SILK_USAGE_DB=usage_db):
        client = _client()
        r = client.post("/deepen", json={"product": "تمور",
                                         "with_volza": True})
        assert r.status_code == 401                       # المصادقة أولاً
        r = client.post("/deepen", json={"product": "تمور",
                                         "with_volza": True},
                        headers={"X-API-Key": "deep-secret"})
        assert r.status_code == 429                       # ثم السقف


def test_deepen_runs_paid_agents_through_context():
    # /deepen يفعّل السياق فيمرّ حارس BaseAgent ويصل منطق الوكيل (keyless=None موسوم).
    from unittest.mock import patch

    with _env(SILK_API_KEY=None, SILK_PAID_DAILY_CAP=None,
              VOLZA_API_KEY=None):
        client = _client()
        with patch("requests.sessions.Session.request",
                   side_effect=OSError("network disabled for hermetic test")):
            r = client.post("/deepen", json={"product": "تمور", "year": 2022,
                                             "with_volza": True})
    assert r.status_code == 200
    row = r.json()["markets"][0]
    assert "volza" in row
    note = row["volza"][0]["note"]
    assert "paid subscription" in note      # وصل _execute (لا حارس التخطي)
