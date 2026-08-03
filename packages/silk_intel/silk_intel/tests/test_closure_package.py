"""حزمة الإغلاق بعد الدمج — أربع تسريبات/فجوات حيّة مؤكَّدة من المُشرِف، كل
واحدة بحارس قفل بسلسلتها الحرفية (silk-operations §4: القفل بالسلسلة الإنتاجية
الحرفية لا بصياغة مثالية). هرمتي بالكامل. Run:
  python3 -m pytest tests/test_closure_package.py -q

البنود:
1. مُطهِّر `silk_render._strip_internal_plumbing` — ثلاث تسريبات: ريبر
   DataPoint(...) (يُحيَّد كاملاً لا نصف-ترجمة)، JSON مضمَّن بمفاتيح
   score/summary، ورموز الحكم بحساسية حالة الأحرف.
2. حاصد التشغيلات اليتيمة — يمسح صفوف "running" العالقة إلى failed ويصالح
   حجوزات الدولار المتسرّبة إلى الفعلي-حتى-الآن.
3. `/diagnostics` يحجز وحدة من السقف المدفوع قبل الفحص (أو SILK_DIAG_EXEMPT=1).
4. سلسلة /markets في parseIntent (web/index.html) لها .catch بنمط خطأ عربي.
"""
from __future__ import annotations

import contextlib
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@contextlib.contextmanager
def _env(**vals):
    old = {k: os.environ.get(k) for k in vals}
    try:
        for k, v in vals.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        yield
    finally:
        for k, v in old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


# ═══ البند ١ — ثلاث تسريبات مُطهِّر _strip_internal_plumbing ═══════════════

def test_datapoint_repr_is_wholly_neutralized_never_half_translated():
    """ريبر DataPoint(...) مسرَّب يُحيَّد **كاملاً**: لا اسم الصنف ولا أي حقل
    خام (value=/source=/confidence=/retrieved_at=/status=) يبقى، ولا
    فرانكنشتاين نصف-مُترجَم («درجة الثقة=0.9») — تُستخرَج القيمة المقروءة."""
    from silk_render import _strip_internal_plumbing
    leaked = ("التوصية مبنية على DataPoint(value='واردات المملكة المتحدة 120 "
              "مليون دولار', source='UN Comtrade', confidence=0.9, "
              "note='قياس ٢٠٢٤', retrieved_at='2026-07-01', status='') وعليه.")
    out = _strip_internal_plumbing(leaked)
    assert "DataPoint(" not in out, out
    for raw in ("value=", "source=", "confidence=", "retrieved_at=", "status="):
        assert raw not in out, f"حقل خام بقي: {raw} في {out}"
    assert "درجة الثقة=" not in out, f"نصف-ترجمة: {out}"
    assert "واردات المملكة المتحدة 120 مليون دولار" in out, out


def test_embedded_json_with_score_and_summary_keys_is_neutralized():
    """JSON مضمَّن خلف بادئة نصية بمفاتيح score/summary (لم تكن في علامات
    البنية الداخلية) يُحيَّد — لا أقواس ولا مفاتيح خام، ويُستخرَج summary."""
    from silk_render import _strip_internal_plumbing
    leaked = ('التوصية: {"score": 0.72, "summary": '
              '"السوق البريطاني واعد للعسل الطبيعي"}')
    out = _strip_internal_plumbing(leaked)
    assert "{" not in out and "}" not in out, out
    assert '"score"' not in out and '"summary"' not in out, out
    assert "السوق البريطاني واعد للعسل الطبيعي" in out, out


def test_verdict_tokens_are_matched_case_insensitively():
    """رموز الحكم الخام تُطابَق بأي حالة أحرف (go/Watch/no-go) لا الكبيرة
    فقط — كانت الحساسية تُبقيها خاماً في المُسلَّم."""
    from silk_render import _strip_internal_plumbing
    for raw in ("الحكم go — مراقبة قبل الدخول.",
                "التوصية Watch على هذا السوق.",
                "النتيجة no-go بوضوح."):
        out = _strip_internal_plumbing(raw)
        assert not re.search(r"\b(conditional-go|no-go|go|watch)\b", out, re.I), (
            f"رمز حكم خام بقي: {out}")


# ═══ البند ٢ — حاصد التشغيلات اليتيمة (running عالق + حجز دولار متسرّب) ═══════

def _seed_stale_running(db, aid_cost=0.8, minutes_ago=45):
    """ازرع صفّ تشغيلة 'running' قديم (updated_at قبل دقائق) بتكلفة-حتى-الآن."""
    import datetime
    import silk_storage as st
    aid = st.create_research_run("عسل طبيعي", "GBR", None, {"product": "عسل"},
                                 path=db, market_name="المملكة المتحدة")
    st.update_research_progress(aid, path=db, cost_usd_estimate=aid_cost)
    old = (datetime.datetime.now()
           - datetime.timedelta(minutes=minutes_ago)).isoformat(timespec="seconds")
    with st._connect(db) as conn:
        conn.execute("UPDATE analyses SET updated_at = ? WHERE id = ?", (old, aid))
    return aid


def test_orphan_reaper_marks_stale_running_failed_and_reconciles_usd(tmp_path):
    """تشغيلة 'running' عالقة (تعطّل عملية) تُوسَم failed، وحجزها الدولاري
    المتسرّب (٣.٠ محجوزة، فعلي-حتى-الآن ٠.٨) يُصالَح إلى الفعلي (٠.٨)."""
    import silk_storage as st
    import silk_usage
    db = str(tmp_path / "silk.db")
    usage_db = str(tmp_path / "usage.db")
    with _env(SILK_USAGE_DB=usage_db, SILK_RESEARCH_EXPECTED_USD="3.0",
              SILK_ORPHAN_STALE_MINUTES="30", SILK_DATA_DIR=None, SILK_DB=None):
        silk_usage.record_usd(3.0, path=usage_db)          # الحجز المسبق
        aid = _seed_stale_running(db, aid_cost=0.8, minutes_ago=45)
        reaped = st.reap_orphan_research_runs(path=db)
        assert aid in reaped, reaped
        assert st.get_research_run(aid, path=db)["status"] == "failed"
        # الحجز صولِح إلى الفعلي-حتى-الآن: ٣.٠ → ٠.٨
        assert abs(silk_usage.usd_spent_today(usage_db) - 0.8) < 1e-6, (
            silk_usage.usd_spent_today(usage_db))


def test_orphan_reaper_leaves_fresh_running_untouched(tmp_path):
    """تشغيلة 'running' حديثة (لُمِست للتوّ) دون عتبة النبضة — لا تُحصَد."""
    import silk_storage as st
    db = str(tmp_path / "silk.db")
    with _env(SILK_ORPHAN_STALE_MINUTES="30", SILK_DATA_DIR=None, SILK_DB=None):
        aid = _seed_stale_running(db, aid_cost=0.5, minutes_ago=2)   # حديثة
        reaped = st.reap_orphan_research_runs(path=db)
        assert aid not in reaped
        assert st.get_research_run(aid, path=db)["status"] == "running"


def test_orphan_reaper_wired_at_startup_and_in_periodic_loop():
    """المكنَس موصول عند الإقلاع (api) وفي حلقة الجدولة الدورية (silk_collectors)."""
    api_src = open("api.py", encoding="utf-8").read()
    coll_src = open("silk_collectors.py", encoding="utf-8").read()
    assert "reap_orphan_research_runs" in api_src, "غير موصول عند الإقلاع"
    assert "reap_orphan_research_runs" in coll_src, "غير موصول في الحلقة الدورية"


# ═══ البند ٣ — /diagnostics يحجز وحدة من السقف المدفوع قبل الفحص ═══════════

def test_diagnostics_reserves_a_paid_unit_and_429s_when_cap_exhausted(tmp_path, monkeypatch):
    """التشخيص يُطلق نداءات مدفوعة حيّة — يحجز وحدة من السقف؛ سقف مُستنفَد =>
    429 قبل أي فحص (لا استنزاف تحت السقف)."""
    from fastapi.testclient import TestClient
    import api
    # لا وصول شبكة داخل الاختبار (نمنعه قبل أيّ فحص حيّ محتمل)
    monkeypatch.setattr("requests.get", lambda *a, **k: (_ for _ in ()).throw(OSError("blocked")))
    with _env(SILK_USAGE_DB=str(tmp_path / "u.db"), SILK_PAID_DAILY_CAP="0",
              SILK_DIAG_EXEMPT=None, SILK_API_KEY=None):
        r = TestClient(api.app).get("/diagnostics")
    assert r.status_code == 429, r.status_code
    assert r.json()["detail"]["error"] == "daily_paid_cap_exhausted"


def test_diagnostics_exempt_flag_bypasses_the_cap(tmp_path, monkeypatch):
    """SILK_DIAG_EXEMPT=1 يُعفي التشخيص من السقف — لا 429 حتى بسقف مُستنفَد."""
    from fastapi.testclient import TestClient
    import api
    import silk_diagnostics
    monkeypatch.setattr(silk_diagnostics, "run_diagnostics",
                        lambda year=2022: {"overall": "ok", "agents_can_work": True,
                                           "sources": []})
    with _env(SILK_USAGE_DB=str(tmp_path / "u.db"), SILK_PAID_DAILY_CAP="0",
              SILK_DIAG_EXEMPT="1", SILK_API_KEY=None):
        r = TestClient(api.app).get("/diagnostics")
    assert r.status_code != 429, r.status_code
    assert r.json().get("agents_can_work") is True


def test_diagnostics_unchanged_when_no_cap_set(tmp_path, monkeypatch):
    """بلا سقف مضبوط: لا حجز ولا 429 — السلوك الافتراضي غير متأثّر (توافق خلفي)."""
    from fastapi.testclient import TestClient
    import api
    import silk_diagnostics
    monkeypatch.setattr(silk_diagnostics, "run_diagnostics",
                        lambda year=2022: {"overall": "ok", "agents_can_work": True,
                                           "sources": []})
    with _env(SILK_USAGE_DB=str(tmp_path / "u.db"), SILK_PAID_DAILY_CAP=None,
              SILK_DIAG_EXEMPT=None, SILK_API_KEY=None):
        r = TestClient(api.app).get("/diagnostics")
    assert r.status_code == 200


# ═══ البند ٤ — سلسلة /markets في parseChat لها .catch بنمط خطأ عربي ═════════

def test_markets_chain_in_parseintent_has_arabic_catch():
    """سلسلة جلب /markets (بناء نيّة الدردشة) لها .catch بأثر عربي مرئي +
    تدهور رشيق — لا رفض صامت يُعلّق مؤشّر الانتظار (عائلة العودة الصامتة #98)."""
    html = open("web/index.html", encoding="utf-8").read()
    # كلا استدعاءَي /markets (رسم القائمة + بناء النيّة) متبوعان بـ.catch.
    assert html.count("base()+\"/markets\"") >= 2, "استدعاء /markets مفقود"
    assert "تعذّر تحميل قائمة الأسواق" in html, "لا .catch عربي على سلسلة /markets"
    # التدهور الرشيق: يعيد المنتج بلا سوق (لا تعليق) بدل الرفض.
    assert "market:null,span:span}" in html or "market:null, span:span}" in html
