"""أقفال الموجة ٣ (LOW) من تدقيق FULL_AUDIT_v2 — Wave 3 low-severity locks.

بنودٌ منخفضةٌ (تنظيف مجلّد مؤقّت + توثيق أعلام/دلالات) — أقفالُ قراءة مصدر
هرمتية بلا شبكة. لا صفّ LESSONS منفصل (بنود توثيق/موارد، الأقفال تكفي).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel: str) -> str:
    with open(os.path.join(_ROOT, rel), encoding="utf-8") as f:
        return f.read()


# ── البند #8 — مجلّدات التصدير المؤقّتة تُنظَّف بعد الإرسال ────────────────────

def test_report_exports_clean_their_temp_dir():
    """report.docx/report.pdf كانا يُنشئان `tempfile.mkdtemp()` لكل طلب لا يُحذَف
    أبداً (FileResponse يبثّ الملف لا مجلّده) فيتراكم على قرص النشر. الآن مجلّد
    واحد لكلٍّ يُنظَّف عبر BackgroundTask بعد الإرسال + تنظيفٌ عند مسار الفشل."""
    api = _read("api.py")
    assert "def _rmtree_bg(" in api, "مساعد التنظيف الخلفي غائب"
    assert "from starlette.background import BackgroundTask" in api, (
        "BackgroundTask غير مستعمَل للتنظيف")
    # كلا التصديرين يُمرّران التنظيف الخلفي لـFileResponse.
    assert api.count("background=_rmtree_bg(_td)") >= 2, (
        "أحد مساري التصدير (docx/pdf) لا يُنظّف مجلّده المؤقّت")
    # ولا يُنشئان mkdtemp متعدّداً غير مُنظَّف داخل الفروع (مجلّد واحد `_td`).
    assert "_td = tempfile.mkdtemp()" in api, "لم يُوحَّد المجلّد المؤقّت للتصدير"
    # تنظيفٌ صريح عند مسار الفشل (501/503) قبل رفع الاستثناء.
    assert api.count("rmtree(_td, ignore_errors=True)") >= 2, (
        "مسار فشل التصدير لا يُنظّف المجلّد المؤقّت")


# ── البند #9 — أعلام الميزات الجديدة موثَّقة في .env.example ──────────────────

def test_new_feature_flags_documented_in_env_example():
    """أعلام الميزتين الجديدتين (تغطية العالم + استقبال الصورة) وضوابطهما كانت
    غائبة عن .env.example فلا يكتشفها المشغّل — أُضيفت ثنائية اللغة."""
    env = _read(".env.example")
    for flag in ("SILK_WORLD_MARKETS", "SILK_IMAGE_INTAKE",
                 "SILK_WORLD_TIER2_MAX", "SILK_INTAKE_MIN_CONFIDENCE",
                 "SILK_GMAPS_ENRICH_GRACE_S"):
        assert f"{flag}=" in env, f"العلم {flag} غير موثَّق في .env.example"


# ── البند #10 — دلالة عدم استرداد وحدة السقف عند الفشل موثَّقة ─────────────────

def test_cap_no_refund_semantics_documented():
    """السقف يحجز **قبل** النداء ولا يُردّ عند الفشل/الفراغ (fail-closed) —
    موثَّق صراحةً كقرار مقصود قرب تعريف SILK_PAID_DAILY_CAP."""
    env = _read(".env.example")
    assert "البند #10" in env and "عدم الاسترداد" in env, (
        "دلالة عدم الاسترداد غير موثَّقة")
    assert "No-refund semantics" in env, "المرآة الإنجليزية غائبة"
