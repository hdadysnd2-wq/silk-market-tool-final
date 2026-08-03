"""اختبارات Stage 2A — إنفاذ المصادر الخادمي (البوابة ١ المعتمدة).

يقفل: (١) سياسة المصادر تُقرَّر في الخادم ولا يستطيع علم عميل إطفاء مصدر مجاني؛
(٢) لوحة المفاتيح تحفظ للخادم فعلاً (allow-list، لا إرجاع للقيم)؛ (٣) قارئ
WGI/LPI/FX يقرأ أخيراً ما يجمعه M2 (قيم حقيقية من المخزن) ويحسب تقلب العملة؛
(٤) التغطية لكل قسم + ملحق الأثر في نموذج العرض — لا فشل صامتاً.
"""
import contextlib
import os
import sys
import tempfile
from unittest import mock

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
    return TestClient(api.create_app()), sys.modules["api"]


def _tmp_store_env():
    d = tempfile.mkdtemp()
    return os.path.join(d, "store.db")


def test_source_policy_is_server_decided_and_client_cannot_disable():
    import pytest
    pytest.importorskip("fastapi"); pytest.importorskip("httpx")
    with _env(SILK_API_KEY=None, SILK_RATE_LIMIT="0",
              SILK_STORE_DB=_tmp_store_env(),
              SEARCH_API_KEY=None, GOOGLE_MAPS_API_KEY=None):
        client, api_mod = _client()
        captured = {}
        def spy(product, **kw):
            captured.update(kw)
            return {"product": product, "classified": False, "markets": [],
                    "hs_code": None, "hs_note": "x", "note": "x"}
        with mock.patch("silk_engine.analyze", spy):
            # العميل يحاول إطفاء كل شيء — الخادم يتجاهله (القاعدة الصلبة).
            r = client.post("/analyze", json={"product": "تمور",
                                              "with_tariffs": False,
                                              "with_faostat": False,
                                              "with_trends": False})
        assert r.status_code == 200
        for flag in ("with_trends", "with_tariffs", "with_faostat",
                     "with_requirements", "with_trend", "with_risk",
                     "with_research"):
            assert captured.get(flag) is True, flag
        # قرار مراجعة التشغيل الحي: الموجة ٣ الاسمية (Serper فقط) زائدة عن
        # حاجتها بعد with_research (المرحلة ٣ تغطي نفس السؤال) — معطَّلة
        # دائماً من سياسة الخادم الآن، والعميل لا يقدر يشغّلها (نفس القاعدة
        # الصلبة: علم العميل لا يُشغِّل ولا يُعطِّل مصدراً).
        for flag in ("with_competitors", "with_channels", "with_importers"):
            assert captured.get(flag) is False, flag
        # المفتاحيّ المجاني: يتبع مفتاح الخادم لا الواجهة.
        assert captured.get("with_websearch") is False
        assert captured.get("with_maps") is False
    with _env(SILK_API_KEY=None, SILK_RATE_LIMIT="0",
              SILK_STORE_DB=_tmp_store_env(),
              SEARCH_API_KEY="srv-key", GOOGLE_MAPS_API_KEY="srv-key"):
        client, api_mod = _client()
        captured = {}
        with mock.patch("silk_engine.analyze", spy):
            client.post("/analyze", json={"product": "تمور"})
        assert captured.get("with_websearch") is True
        assert captured.get("with_maps") is True


def test_settings_keys_persist_serverside_allowlisted_and_authgated():
    import pytest
    pytest.importorskip("fastapi"); pytest.importorskip("httpx")
    db = _tmp_store_env()
    with _env(SILK_API_KEY="sekret", SILK_RATE_LIMIT="0", SILK_STORE_DB=db,
              SEARCH_API_KEY=None):
        client, _ = _client()
        body = {"keys": {"SEARCH_API_KEY": "abc123", "EVIL_KEY": "x"}}
        assert client.post("/settings/keys", json=body).status_code == 401
        r = client.post("/settings/keys", json=body,
                        headers={"X-API-Key": "sekret"})
        assert r.status_code == 200
        assert r.json() == {"saved": ["SEARCH_API_KEY"], "rejected": ["EVIL_KEY"]}
        assert os.environ.get("SEARCH_API_KEY") == "abc123"   # فوري للعملية
        import silk_store
        with silk_store.connect() as conn:                    # ومُثبَت في المخزن
            v = conn.execute("SELECT value FROM settings WHERE key='SEARCH_API_KEY'"
                             ).fetchone()[0]
        assert v == "abc123"
    os.environ.pop("SEARCH_API_KEY", None)


def test_risk_reader_serves_real_store_facts_and_fx_volatility():
    from conftest import block_network
    db = _tmp_store_env()
    with _env(SILK_STORE_DB=db):
        import silk_store, silk_engine
        silk_store.migrate()
        silk_store.upsert_indicator("ARE", "PV.EST", 2023, 0.7, "World Bank", .95)
        silk_store.upsert_indicator("ARE", "RQ.EST", 2023, 0.9, "World Bank", .95)
        silk_store.upsert_indicator("ARE", "LP.LPI.OVRL.XQ", 2023, 4.0,
                                    "World Bank", .95)
        for y, v in ((2020, 3.67), (2021, 3.67), (2022, 3.67), (2023, 3.67)):
            silk_store.upsert_indicator("ARE", "PA.NUS.FCRF", y, v,
                                        "World Bank", .95)
        with block_network():
            res = silk_engine.analyze("تمور", countries=[{"iso3": "ARE",
                                                          "m49": "784"}],
                                      year=2023, with_risk=True)
        risk = res["markets"][0]["risk"]
        real = [f for f in risk if f.value is not None]
        assert len(real) == 4                       # 3 مؤشرات + تقلب العملة
        vol = [f for f in real if "تقلب" in f.note][0]
        assert vol.value == 0.0                     # الدرهم مربوط: تقلب صفر — حقيقي
        assert any("مخزن الحقائق" in f.note for f in real)
        # مخزن فارغ + شبكة مقطوعة => فجوات موسومة لا اختلاق.
    with _env(SILK_STORE_DB=_tmp_store_env()):
        import importlib, silk_store as s2
        importlib.reload(s2); s2.migrate()
        import silk_engine
        from conftest import block_network as bn
        with bn():
            res2 = silk_engine.analyze("تمور", countries=[{"iso3": "MAR",
                                                           "m49": "504"}],
                                       year=2023, with_risk=True)
        risk2 = res2["markets"][0]["risk"]
        assert risk2 and all(f.value is None for f in risk2)


def test_view_has_section_coverage_and_provenance_appendix():
    from conftest import block_network
    import silk_engine, silk_render
    with _env(SILK_STORE_DB=_tmp_store_env()):
        with block_network():
            res = silk_engine.analyze("تمور", countries=[{"iso3": "ARE",
                                                          "m49": "784"}],
                                      year=2023, with_tariffs=True,
                                      with_requirements=True, with_risk=True)
        view = silk_render.build_view(res)
    cov = view["markets"][0]["section_coverage"]
    for sec in ("market_size", "demand", "regulatory", "risk"):
        assert sec in cov and "score" in cov[sec]
    assert cov["regulatory"]["attempted"] >= 1
    prov = view["provenance"]
    assert prov and all({"source", "attempted", "contributed"} <= set(b)
                        for b in prov)
    # لا فشل صامتاً: مصادر الشبكة المقطوعة تظهر بمحاولاتها وملاحظات فشلها.
    wb = [b for b in prov if b["source"] == "World Bank"]
    assert wb and wb[0]["attempted"] >= 1
    assert wb[0]["contributed"] == 0 and wb[0]["failures"]


def test_client_cannot_reenable_retired_wave3_named_agents():
    """قرار مراجعة التشغيل الحي: الموجة ٣ الاسمية معطَّلة دائماً — العميل لا
    يقدر يعيد تشغيلها حتى لو أرسلها صراحةً true (نفس القاعدة الصلبة، بالاتجاه
    المعاكس: علم العميل لا يُشغِّل مصدراً كما لا يُطفئه)."""
    import pytest
    pytest.importorskip("fastapi"); pytest.importorskip("httpx")
    with _env(SILK_API_KEY=None, SILK_RATE_LIMIT="0",
              SILK_STORE_DB=_tmp_store_env()):
        client, _ = _client()
        captured = {}

        def spy(product, **kw):
            captured.update(kw)
            return {"product": product, "classified": False, "markets": [],
                    "hs_code": None, "hs_note": "x", "note": "x"}

        with mock.patch("silk_engine.analyze", spy):
            client.post("/analyze", json={"product": "تمور",
                                          "with_competitors": True,
                                          "with_channels": True,
                                          "with_importers": True})
        for flag in ("with_competitors", "with_channels", "with_importers"):
            assert captured.get(flag) is False, flag


def test_market_size_cross_validation_flags_20pct_divergence():
    # تحقق تقاطعي: صف العالم 100 مقابل مجموع شركاء 60 => تباين 40% يُعلَّم وتنخفض الثقة.
    import silk_data_layer_v2 as v2
    recs = [{"partnerCode": "0", "primaryValue": 100.0},
            {"partnerCode": "682", "primaryValue": 60.0}]
    with mock.patch.object(v2, "comtrade_trade", return_value=recs):
        mi = v2.market_imports("080410", "784", 2023)
    assert mi["total_usd"] == 100.0
    assert "تباين مصادر 40%" in mi["xval_note"]
    # وبلا تباين (100 مقابل 95) لا علم.
    recs2 = [{"partnerCode": "0", "primaryValue": 100.0},
             {"partnerCode": "682", "primaryValue": 95.0}]
    with mock.patch.object(v2, "comtrade_trade", return_value=recs2):
        mi2 = v2.market_imports("080410", "784", 2023)
    assert mi2["xval_note"] == ""
