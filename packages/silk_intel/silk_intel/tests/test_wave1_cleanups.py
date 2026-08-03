"""اختبارات الموجة ١ (النظافة) — hermetic wave-1 cleanup tests (no network).

تغطي: الأغلفة الصامتة صارت موسومة، لا افتراض WATCH، عمودا outcome، نقطة PATCH،
ونموذج samples/ صالح. Run:  python3 -m pytest tests/ -q
"""
import contextlib
import json
import os
import socket
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import silk_engine as engine

# مرجع قانوني موحَّد (conftest.py) — راجع تعليق test_smoke.py لسبب توحيد
# النسخ المحلية المكرَّرة (تسريب اتصال مجمَّع عبر جلسة requests المشتركة).
from conftest import block_network as _block_network


def test_enrichment_wrapper_exception_yields_noted_datapoint():
    # استثناء غير متوقع من وكيل إثراء => DataPoint(None, note=السبب) لا [] صامتة.
    from unittest.mock import patch
    import silk_trends_agent

    with patch.object(silk_trends_agent.TrendsAgent, "run",
                      side_effect=RuntimeError("boom-inside-agent")):
        with _block_network():
            res = engine.analyze("تمور",
                                 countries=[{"iso3": "ARE", "m49": "784"}],
                                 year=2022, with_trends=True)
    row = res["markets"][0]
    assert len(row["trends"]) == 1
    dp = row["trends"][0]
    assert dp.value is None and dp.confidence == 0.0
    assert "enrichment error" in dp.note and "boom-inside-agent" in dp.note
    assert dp.source == "Google Trends"


def test_enrichment_wrapper_tariff_exception_noted():
    # نفس الضمان للغلاف أحادي القيمة (tariff): None صار DataPoint موسومًا.
    from unittest.mock import patch
    import silk_tariffs_agent

    with patch.object(silk_tariffs_agent.TariffsAgent, "run",
                      side_effect=RuntimeError("tariff-agent-crash")):
        with _block_network():
            res = engine.analyze("تمور",
                                 countries=[{"iso3": "ARE", "m49": "784"}],
                                 year=2022, with_tariffs=True)
    dp = res["markets"][0]["tariff"]
    assert dp is not None and dp.value is None
    assert "enrichment error" in dp.note and "tariff-agent-crash" in dp.note


def test_ai_verdict_no_watch_default_on_unparseable_reply():
    # ردّ غير JSON من كلود => verdict=None صريح (لا وسم WATCH مختلق).
    # (الموجة ٤ وحّدت الحكم في silk_synthesis — نفس الضمان على المدخل الموحّد.)
    from unittest.mock import patch
    import silk_synthesis as synth

    with patch.object(synth, "_call", return_value="آسف، لا أستطيع إخراج JSON"):
        out = synth.synthesize([], product="تمور", market="مصر", with_ai=True)
    v = out.get("ai")
    assert v is not None
    assert v["verdict"] is None                  # لا افتراض
    assert "لا أستطيع" in v["reasoning"]          # النص محفوظ كتعليل
    assert out["synthesis_stage"] == 2           # المرحلتان عملتا


def test_ai_report_absence_is_visible_not_hidden():
    # with_ai بلا مفتاح => result["report"]=None + report_note (لا حذف صامت).
    os.environ.pop("ANTHROPIC_API_KEY", None)
    with _block_network():
        res = engine.analyze("تمور", countries=[{"iso3": "ARE", "m49": "784"}],
                             year=2022, with_ai=True)
    assert "report" in res and res["report"] is None
    assert "report_note" in res and res["report_note"]


def test_outcome_columns_and_set_outcome_roundtrip():
    # عمودا outcome/outcome_date موجودان، والتسجيل يعمل ولا يمسّ بيانات التحليل.
    import silk_storage as storage

    db = os.path.join(tempfile.mkdtemp(), "outcome.db")
    fake = {"product": "demo", "hs_code": "000000", "year": 2022,
            "preliminary": True, "markets": []}
    aid = storage.save_analysis(fake, db)
    assert storage.set_outcome(aid, "دخلنا السوق — GO confirmed", db) is True
    meta = [r for r in storage.list_analyses(db) if r["id"] == aid][0]
    assert meta["outcome"] == "دخلنا السوق — GO confirmed"
    assert meta["outcome_date"]                      # تاريخ اليوم مسجّل
    assert storage.get_analysis(aid, db)["product"] == "demo"  # البيانات كما هي
    assert storage.set_outcome(99999, "x", db) is False        # لا إنشاء ضمني


def test_silk_db_env_redirects_storage():
    # SILK_DB يوجّه قاعدة التحليلات وقت النداء (نشر بقرص دائم — Railway volume)
    # دون تمرير path صريح؛ يُقرأ عند كل نداء لا عند الاستيراد.
    import silk_storage as storage

    db = os.path.join(tempfile.mkdtemp(), "envdir", "silk_env.db")
    old = os.environ.get("SILK_DB")
    os.environ["SILK_DB"] = db
    try:
        aid = storage.save_analysis(
            {"product": "env-demo", "hs_code": "000000", "markets": []})
        assert os.path.exists(db)                        # كُتبت حيث وجّه المتغير
        assert storage.get_analysis(aid)["product"] == "env-demo"
        assert any(r["id"] == aid for r in storage.list_analyses())
    finally:
        if old is None:
            os.environ.pop("SILK_DB", None)
        else:
            os.environ["SILK_DB"] = old


def test_outcome_migration_on_old_schema_db():
    # قاعدة قديمة بلا العمودين => init_db يرحّلها بلا مساس بالصفوف القائمة.
    import sqlite3
    import silk_storage as storage

    db = os.path.join(tempfile.mkdtemp(), "old.db")
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE analyses (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                 "product TEXT, hs_code TEXT, year INTEGER, created_at TEXT, "
                 "preliminary INTEGER, json_blob TEXT)")
    conn.execute("INSERT INTO analyses (product, json_blob) VALUES (?, ?)",
                 ("legacy", '{"product": "legacy"}'))
    conn.commit()
    conn.close()
    storage.init_db(db)
    rows = storage.list_analyses(db)
    assert rows[0]["product"] == "legacy"            # الصف القديم سليم
    assert rows[0]["outcome"] is None                # العمود الجديد موجود وفارغ
    assert storage.set_outcome(rows[0]["id"], "entered", db) is True


def test_patch_outcome_endpoint():
    # PATCH /analyses/{id}/outcome: يسجّل، و404 للمفقود، و422 للفارغ.
    import pytest
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    import api
    import silk_storage as storage

    db = os.path.join(tempfile.mkdtemp(), "api_outcome.db")
    aid = storage.save_analysis({"product": "demo", "markets": []}, db)
    # وجّه الوحدة لقاعدة الاختبار عبر المسار الافتراضي المؤقت.
    saved = storage._DEFAULT_PATH
    storage._DEFAULT_PATH = db
    try:
        client = TestClient(api.create_app())
        r = client.patch(f"/analyses/{aid}/outcome",
                         json={"outcome": "WATCH صار GO"})
        assert r.status_code == 200 and r.json()["recorded"] is True
        assert r.json()["outcome"] == "WATCH صار GO"
        assert client.patch("/analyses/424242/outcome",
                            json={"outcome": "x"}).status_code == 404
        assert client.patch(f"/analyses/{aid}/outcome",
                            json={"outcome": "  "}).status_code == 422
    finally:
        storage._DEFAULT_PATH = saved


def test_sample_json_exists_and_valid():
    # قاعدة samples/ (١٠.٦): نموذج فعلي محفوظ بالمستودع وقابل للتحميل.
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, "samples", "analysis_latest.json")
    assert os.path.exists(path)
    data = json.loads(open(path, encoding="utf-8").read())
    assert data["product"] and data["hs_code"] == "080410"
    assert data["preliminary"] is True and data["markets"]
