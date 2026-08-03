"""اختبارات P5 — حكم كلود على المسار الرئيسي، سنة أحدث، ومرادف مفتاح Serper.

بلاغ المالك: «كلود العادي يتفوق على المنصة» — لأن حكم كلود (المرحلة ٢ من
التوليف) وتقريره كانا حبيسي /deepen المدفوع، فالمسار الرئيسي لا يرى إلا
اللجنة الحتمية؛ و«لا معلومات مصدرها قوقل» — لأن مفتاح Serper المضبوط باسم
شائع (SERPER_API_KEY) كان يُهمَل بصمت؛ و«يغطي 2025» — لأن السنة الافتراضية
كانت today-2 والواجهة تفرض CURY-2. يقفل هذا الملف:
(١) /analyze يمرّر with_ai=True متى كان مفتاح كلود مضبوطاً ومحمياً (H2)؛
(٢) بلا مفتاح كلود يبقى with_ai=False — لا نداء يُحاوَل؛
(٣) السنة الافتراضية today-1 (التراجع المعلن يغطي غير المنشور)؛
(٤) SERPER_API_KEY مرادف مقبول لـ SEARCH_API_KEY (الوكيل والسياسة معاً)؛
(٥) /health يحمل كتلة sources تشخيصية (وجود/غياب فقط، لا قيم).
Run:  python3 -m pytest tests/test_p5_judge_and_reach.py -q
"""
import contextlib
import datetime
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@contextlib.contextmanager
def _env(**vals):
    """اضبط متغيرات بيئة مؤقتًا — set env vars, always restoring the old state."""
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


def test_default_year_is_today_minus_one():
    import silk_engine
    assert silk_engine._default_year() == datetime.date.today().year - 1


def _client_and_api():
    import pytest
    pytest.importorskip("fastapi"); pytest.importorskip("httpx")
    import importlib
    import api
    importlib.reload(api)
    from fastapi.testclient import TestClient
    return TestClient(api.create_app()), api


def test_analyze_passes_with_ai_when_claude_key_protected():
    """مفتاح كلود + SILK_API_KEY => المحرّك يستلم with_ai=True (حكم المرحلة ٢)."""
    with _env(ANTHROPIC_API_KEY="k", SILK_API_KEY="s",
              SILK_PAID_DAILY_CAP=None, SILK_RATE_LIMIT="0"):
        client, _ = _client_and_api()
        with mock.patch("silk_engine.analyze",
                        return_value={"markets": []}) as eng:
            r = client.post("/analyze", json={"product": "عسل"},
                            headers={"X-API-Key": "s"})
        assert r.status_code == 200
        assert eng.call_args.kwargs.get("with_ai") is True


def test_analyze_keeps_with_ai_false_without_claude_key():
    with _env(ANTHROPIC_API_KEY=None, SILK_API_KEY=None,
              SILK_RATE_LIMIT="0"):
        client, _ = _client_and_api()
        with mock.patch("silk_engine.analyze",
                        return_value={"markets": []}) as eng:
            r = client.post("/analyze", json={"product": "عسل"})
        assert r.status_code == 200
        assert eng.call_args.kwargs.get("with_ai") is False


def test_analyze_blocks_ai_when_key_unprotected_h2():
    """مفتاح كلود بلا SILK_API_KEY => حارس H2: with_ai=False + ملاحظة معلنة."""
    with _env(ANTHROPIC_API_KEY="k", SILK_API_KEY=None, SILK_RATE_LIMIT="0"):
        client, _ = _client_and_api()
        with mock.patch("silk_engine.analyze",
                        return_value={"markets": []}) as eng:
            r = client.post("/analyze", json={"product": "عسل"})
        assert r.status_code == 200
        assert eng.call_args.kwargs.get("with_ai") is False
        assert "SILK_API_KEY" in r.json().get("ai_extras_note", "")


def test_serper_alias_accepted_by_agent_and_policy():
    """SERPER_API_KEY وحده يكفي: search_key() يجده والسياسة تفعّل websearch."""
    from silk_websearch_agent import search_key
    with _env(SEARCH_API_KEY=None, SERPER_API_KEY="alias-key"):
        assert search_key() == "alias-key"
    with _env(SEARCH_API_KEY="primary", SERPER_API_KEY="alias-key"):
        assert search_key() == "primary"      # SEARCH_API_KEY أعلى سلطة
    with _env(SEARCH_API_KEY=None, SERPER_API_KEY=None):
        assert search_key() == ""
    # السياسة الخادمية: المرادف وحده يفعّل with_websearch.
    with _env(SEARCH_API_KEY=None, SERPER_API_KEY="alias-key",
              ANTHROPIC_API_KEY=None, SILK_RATE_LIMIT="0"):
        client, _ = _client_and_api()
        with mock.patch("silk_engine.analyze",
                        return_value={"markets": []}) as eng:
            client.post("/analyze", json={"product": "عسل"})
        assert eng.call_args.kwargs.get("with_websearch") is True


def test_health_sources_block_states_not_values():
    """كتلة sources في /health: حالة كل مصدر وسببها — بلا أي قيمة مفتاح."""
    with _env(ANTHROPIC_API_KEY="secret-claude", SILK_API_KEY=None,
              SEARCH_API_KEY=None, SERPER_API_KEY=None,
              GOOGLE_MAPS_API_KEY=None, COMTRADE_API_KEY=None):
        client, _ = _client_and_api()
        body = client.get("/health").json()
        src = body["sources"]
        assert "SILK_API_KEY" in src["claude"]        # الحجب مُعلَن بسببه
        assert src["google_search_serper"].startswith("off")
        assert src["google_maps"].startswith("off")
        assert "preview" in src["comtrade"]
        assert "secret-claude" not in str(body)       # لا تسريب قيم
    with _env(ANTHROPIC_API_KEY="k", SILK_API_KEY="s",
              SERPER_API_KEY="alias", SEARCH_API_KEY=None):
        client, _ = _client_and_api()
        src = client.get("/health").json()["sources"]
        assert src["claude"] == "on"
        assert src["google_search_serper"] == "on"
