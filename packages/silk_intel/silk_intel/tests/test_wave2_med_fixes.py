"""أقفال الموجة ٢ (MED) من تدقيق FULL_AUDIT_v2 — Wave 2 medium-severity locks.

هرمتي بالكامل (قاعدة SQLite مؤقتة، بلا شبكة). كل دالة تقفل بنداً واحداً من
أوامر المالك للموجة ٢ فتُفشِل على عودة عائلته.
"""
from __future__ import annotations

import contextlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@contextlib.contextmanager
def _env(**vals):
    """اضبط متغيّرات بيئة مع استعادة مضمونة (None => احذف المتغيّر)."""
    old = {k: os.environ.get(k) for k in vals}
    try:
        for k, v in vals.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = str(v)
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _seed_failed_run(db, cost=0.8):
    """ازرع صفّ تشغيلة فشلت رشيقاً اليوم بتكلفة-حتى-الآن (بلا مصالحة بعد)."""
    import silk_storage as st
    aid = st.create_research_run("عسل طبيعي", "GBR", None, {"product": "عسل"},
                                 path=db, market_name="المملكة المتحدة")
    st.update_research_progress(aid, path=db, cost_usd_estimate=cost)
    st.mark_research_failed(aid, "boom", path=db)
    return aid


# ── البند #3 — تشغيلةٌ تفشل رشيقاً تُصالِح حجزها الدولاري (idempotent) ─────────

def test_failed_research_run_reconciles_reservation(tmp_path):
    """تشغيلةٌ حجزت ٣.٠$ ثم فشلت رشيقاً (mark_research_failed) — المصالحة تُبدِّل
    الحجز بالفعلي-حتى-الآن (٠.٨$)، فلا يبقى ٣.٠$ محجوزاً يسدّ السقف اليومي."""
    import silk_storage as st
    import silk_usage
    db = str(tmp_path / "silk.db")
    usage_db = str(tmp_path / "usage.db")
    with _env(SILK_USAGE_DB=usage_db, SILK_RESEARCH_EXPECTED_USD="3.0",
              SILK_DATA_DIR=None, SILK_DB=None):
        silk_usage.record_usd(3.0, path=usage_db)      # الحجز المسبق
        aid = _seed_failed_run(db, cost=0.8)
        assert st.reconcile_failed_run_usd(aid, path=db) is True
        assert abs(silk_usage.usd_spent_today(usage_db) - 0.8) < 1e-6, (
            silk_usage.usd_spent_today(usage_db))


def test_failed_run_reconcile_is_idempotent(tmp_path):
    """استدعاءٌ ثانٍ (المسار الفاشل + المكنَس على الصفّ نفسه) لا يخصم مرّتين —
    الوسم `usd_reconciled` يمنع الخصم المزدوج (عقد ذرّي الفكرة)."""
    import silk_storage as st
    import silk_usage
    db = str(tmp_path / "silk.db")
    usage_db = str(tmp_path / "usage.db")
    with _env(SILK_USAGE_DB=usage_db, SILK_RESEARCH_EXPECTED_USD="3.0",
              SILK_DATA_DIR=None, SILK_DB=None):
        silk_usage.record_usd(3.0, path=usage_db)
        aid = _seed_failed_run(db, cost=0.8)
        assert st.reconcile_failed_run_usd(aid, path=db) is True
        assert st.reconcile_failed_run_usd(aid, path=db) is False   # لا خصم ثانٍ
        assert abs(silk_usage.usd_spent_today(usage_db) - 0.8) < 1e-6


def test_reaper_also_sweeps_unreconciled_failed_rows(tmp_path):
    """المكنَس يمسح أيضاً صفوف 'failed' غير المُصالَحة (فشلت قبل الإصلاح أو تعطّلت
    بين الوسم والمصالحة) — دلو اليوم فقط، مرّة واحدة."""
    import silk_storage as st
    import silk_usage
    db = str(tmp_path / "silk.db")
    usage_db = str(tmp_path / "usage.db")
    with _env(SILK_USAGE_DB=usage_db, SILK_RESEARCH_EXPECTED_USD="3.0",
              SILK_ORPHAN_STALE_MINUTES="30", SILK_DATA_DIR=None, SILK_DB=None):
        silk_usage.record_usd(3.0, path=usage_db)
        aid = _seed_failed_run(db, cost=0.5)            # فشل بلا مصالحة
        st.reap_orphan_research_runs(path=db)           # يمسح الـ'failed' أيضاً
        assert abs(silk_usage.usd_spent_today(usage_db) - 0.5) < 1e-6, (
            silk_usage.usd_spent_today(usage_db))
        # المكنَس ثانيةً لا يخصم (الصفّ موسوم الآن)
        st.reap_orphan_research_runs(path=db)
        assert abs(silk_usage.usd_spent_today(usage_db) - 0.5) < 1e-6


def test_api_fail_paths_reconcile_the_reservation():
    """المساران المتزامن والخلفي لـ/research يستدعيان reconcile_failed_run_usd
    فور mark_research_failed (قراءة مصدر — لا يبقى حجزٌ متسرّب)."""
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "api.py"), encoding="utf-8").read()
    assert src.count("reconcile_failed_run_usd(analysis_id)") >= 2, (
        "أحد مساري الفشل (متزامن/خلفي) لا يُصالِح الحجز")


# ── البند #6 — كلفة نداء رؤية الاستقبال تُقاس بالدولار (لا العدّاد فقط) ────────

def _png() -> str:
    import base64
    return base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64).decode()


def test_intake_vision_cost_is_usd_metered(tmp_path):
    """نداء رؤية الاستقبال (خارج تشغيلة بحث) كان يُقاس بالعدّاد فقط فلا يظهر
    إنفاقه في السقف الدولاري ولا `?economics`. الآن يُفتَح عدّاد حوله وتُسجَّل
    كلفته الفعلية في دفتر اليوم الدولاري (يظهر في usd_spent_today)."""
    import importlib
    from unittest import mock
    from fastapi.testclient import TestClient
    import silk_llm_provider as prov
    import silk_context
    import silk_usage
    usage_db = str(tmp_path / "usage.db")

    def _vision_records(self, system, text, image_b64, media_type,
                        max_tokens, model, timeout):
        # يحاكي نداءً ناجحاً يسجّل رموزه في العدّاد النشط (كالمزوّد الحقيقي)
        silk_context.record_llm_usage(model, 500, 200)
        return '{"product_name_ar":"تمر","readable":true,"confidence":0.9}'

    with _env(SILK_IMAGE_INTAKE="1", ANTHROPIC_API_KEY="sk-test",
              SILK_API_KEY="secret", SILK_USAGE_DB=usage_db,
              SILK_DATA_DIR=None, SILK_DB=None):
        import api
        importlib.reload(api)
        client = TestClient(api.create_app())
        prov.reset_provider()
        with mock.patch.object(prov.AnthropicProvider, "complete_vision",
                               _vision_records), \
             mock.patch("requests.post",
                        side_effect=OSError("net blocked for offline test")):
            r = client.post("/products/intake",
                            json={"image_base64": _png(),
                                  "media_type": "image/png"},
                            headers={"X-API-Key": "secret"})
        assert r.status_code == 200 and r.json()["ok"] is True, r.text
        assert silk_usage.usd_spent_today(usage_db) > 0, (
            "كلفة نداء الرؤية لم تُسجَّل في الدفتر الدولاري")
        prov.reset_provider()
    importlib.reload(__import__("api"))


# ── البند #7 — أزرار التصدير تُعطَّل أثناء الجلب (لا نقر مزدوج) ────────────────

def _read_repo(rel: str) -> str:
    return open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), rel), encoding="utf-8").read()


def test_export_buttons_disable_during_fetch():
    """نقرٌ مزدوج على «تصدير PDF» كان يُطلِق تحويلَي soffice على الخادم + تنزيلاً
    مكرّراً — الأزرار الآن تُعطَّل أثناء أيّ تصدير وتُعاد عند اكتماله/فشله."""
    html = _read_repo("web/index.html")
    assert "function _expBusy(" in html, "صمّام تعطيل التصدير غائب"
    assert "if(S.exportBusy){" in html, "حارس النقر المزدوج غائب"
    # يعطّل الأزرار الثلاثة، ويعيدها في نهاية كلّ مسار (pdf/docx/md).
    assert '["#pdfBtn","#wordBtn","#mdBtn"]' in html, "لا يعطّل كل أزرار التصدير"
    assert html.count(".then(_done,_done)") >= 3, (
        "أحد مسارات التصدير لا يعيد تفعيل الأزرار عند الاكتمال/الفشل")


# ── البند #4 — enrich-leads بمهلة آمنة للبروكسي + تصريح «قد يكون جارياً» ──────

def test_enrich_leads_grace_is_proxy_safe_by_default():
    """المهلة المتزامنة الافتراضية كانت ٣٠٠ث فتقطعها بوّابة النشر بلا جسم — الآن
    آمنة للبروكسي (≤٦٠ث)، وخيط الكشط يواصل ويخزّن ذاتياً فإعادة الضغط تجلبه."""
    src = _read_repo("api.py")
    import re
    m = re.search(r'SILK_GMAPS_ENRICH_GRACE_S", "(\d+)"', src)
    assert m, "مهلة enrich-leads غير موجودة"
    assert int(m.group(1)) <= 60, f"المهلة الافتراضية {m.group(1)}ث تتجاوز حدّ البروكسي"
    # الردّ يحمل تصريح «قد يكون جارياً» + اقتراح إعادة المحاولة (لا زعم «لا شيء»).
    assert '"processing": processing' in src, "علم processing غائب من ردّ enrich-leads"
    assert "أعد الضغط بعد قليل" in src, "اقتراح إعادة المحاولة غائب"


# ── البند #5 — تماثل /diagnostics موثَّق (قرار مقصود لا سهو) ──────────────────

def test_diagnostics_asymmetry_is_documented():
    """/diagnostics لا يحمل حارس _unprotected_paid_keys 503 كبقية المسارات
    المدفوعة عمداً (أداة اختبار مفاتيح قبل ضبط المصادقة) — القرار موثَّق صراحةً
    في المصدر، وحدّه الفعليّ حجزُ السقف المدفوع لا حارس 503."""
    src = _read_repo("api.py")
    assert "البند #5" in src and "أداة اختبار المفاتيح قبل ضبط" in src, (
        "تماثل /diagnostics غير موثَّق كقرار مقصود")
    # وحدّه الفعليّ قائم: حجز السقف المدفوع (try_reserve_paid_calls) في المسار.
    diag = src[src.index('@app.get("/diagnostics")'):]
    assert "try_reserve_paid_calls(1)" in diag[:3000], "حدّ السقف المدفوع غائب"
