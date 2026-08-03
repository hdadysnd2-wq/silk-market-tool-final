"""Wave 3 §8 — تدرّجُ بوابة الأسلوب + النمطُ السياقيّ للثقة + خُلاصةٌ مطبوعة.

قرار المُشرِف §8:
- الثقة: نمطٌ **سياقيّ** `(ثقة|confidence)\\s*[:=]?\\s*0\\.\\d` => FAIL. لا صيدَ
  كسورٍ مجرّدة («0.6 مليون» مشروع).
- أدوات الربط والأرقام المفتاحية مُدرَّجة: ≤٢ تمرّ، ٣–٤ WARN، ≥٥ FAIL.
- خُلاصةُ الأسلوب (عدّادات) تُطبَع **دائمًا** — WARN مفحوصٌ (كمبدأ §4).
هرمتيّ بالكامل.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import silk_quality_gate as G  # noqa: E402


def _view(text: str) -> dict:
    return {"deep_research": {
        "report": {"text": "## 1. الخلاصة\n" + text}, "missions": {},
        "analyst": {"by_category": {}, "missing_categories": []},
        "verdict": {}}}


# ── الثقة: نمطٌ سياقيّ (FAIL) بلا إيجابٍ كاذبٍ على المقادير ─────────────────
def test_confidence_contextual_pattern_fails_arabic_and_english():
    for bad in ["القرار مبنيّ على ثقة 0.6 في البيانات.",
                "verdict WATCH — confidence 0.8 مسجّلة.",
                "الحصة (ثقة 0.4) غير متحقّقة."]:
        checks = [f["check"] for f in G._check_style(bad)]  # noqa: SLF001
        out = G.run_quality_gate(_view(bad))
        assert "raw_confidence" in {f["check"] for f in out["findings"]} \
            or out["verdict"] == G.FAIL, bad
        # النمط السياقيّ يُطلِق raw_confidence في بوابة الجودة الكاملة:
        assert out["verdict"] == G.FAIL, bad
        del checks


def test_confidence_no_false_positive_on_bare_magnitudes():
    """لا صيدَ كسورٍ مجرّدة: مقاديرُ البيانات المشروعة لا تُطلِق raw_confidence."""
    for ok in ["بلغت الواردات 0.6 مليون طن في 2023.",
               "ارتفع المؤشر إلى 3.5 نقطة ثم 0.9 نقطة.",
               "النمو 9.5% سنويًّا."]:
        out = G.run_quality_gate(_view(ok))
        assert "raw_confidence" not in {f["check"] for f in out["findings"]}, ok


# ── أدوات الربط: تدرّج ٣–٤ WARN / ≥٥ FAIL ──────────────────────────────────
# نؤكّد على مستوى الآلية (اسمُ الفحص ± عضويّتُه في مجموعة إطلاق FAIL)، لا على
# حكم run_quality_gate الكامل — فمقتطفٌ صغير يُفشِل بنيويًّا (section_structure)
# فيحجب تمييزَ الطبقة. العضويّة في _REGRESSION_GUARD_FIRED هي عقدُ التصعيد.
def test_connector_3_4_is_warn_tier_not_fail_trigger():
    txt = "من ناحية أ. من ناحية ب. من ناحية ج."          # ×3
    checks = {f["check"] for f in G._check_style(txt)}  # noqa: SLF001
    assert "style_connector_overuse" in checks
    assert "style_connector_excess" not in checks
    # WARN: لا يُطلِق FAIL بذاته (خارج مجموعة الحرس)
    assert "style_connector_overuse" not in G._REGRESSION_GUARD_FIRED  # noqa: SLF001


def test_connector_5plus_is_hard_fail_trigger():
    txt = ("من ناحية أ. من ناحية ب. من ناحية ج. من ناحية د. "
           "من ناحية هـ.")                                 # ×5
    checks = {f["check"] for f in G._check_style(txt)}  # noqa: SLF001
    assert "style_connector_excess" in checks
    # FAIL: مُدرَج في مجموعة الحرس => يُصعِّد الحكم إلى FAIL حين يُطلِق
    assert "style_connector_excess" in G._REGRESSION_GUARD_FIRED  # noqa: SLF001


def test_broadened_connector_list_detected():
    txt = ("علاوة على ذلك أ. علاوة على ذلك ب. علاوة على ذلك ج.")  # ×3
    checks = {f["check"] for f in G._check_style(txt)}  # noqa: SLF001
    assert "style_connector_overuse" in checks


# ── الأرقام المفتاحية: تدرّج ٣–٤ WARN / ≥٥ FAIL ────────────────────────────
def test_key_figure_3_4_is_warn_tier():
    txt = "55.28% ثم 55.28% ثم 55.28%."                    # ×3
    checks = {f["check"] for f in G._check_style(txt)}  # noqa: SLF001
    assert "style_repeated_key_figure" in checks
    assert "style_repeated_key_figure_excess" not in checks
    assert "style_repeated_key_figure" not in G._REGRESSION_GUARD_FIRED  # noqa: SLF001


def test_key_figure_5plus_is_hard_fail_trigger():
    txt = "55.28% " * 5                                     # ×5
    checks = {f["check"] for f in G._check_style(txt)}  # noqa: SLF001
    assert "style_repeated_key_figure_excess" in checks
    assert "style_repeated_key_figure_excess" in G._REGRESSION_GUARD_FIRED  # noqa: SLF001


# ── الخُلاصة تُطبَع دائمًا (كمبدأ §4) ───────────────────────────────────────
def test_style_digest_counts_and_tiers():
    d = G.style_digest("من ناحية أ. من ناحية ب. علاوة على ذلك ج. 55.28% 55.28%")
    assert d["connectors"]["من ناحية"] == 2
    assert d["connectors"]["علاوة على ذلك"] == 1
    assert d["key_figures"]["55.28%"] == 2
    assert G._style_tier(2) == "ok" and G._style_tier(3) == "WARN" \
        and G._style_tier(5) == "FAIL"  # noqa: SLF001


def test_style_digest_always_printed_for_sample_report(capsys):
    """§4-principle: اطبع خُلاصة الأسلوب دائمًا للتقرير العيّنة — مفحوصةٌ في CI."""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "samples", "research_report_latest.md")
    text = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
    digest = G.format_style_digest(text)
    with capsys.disabled():
        print("\n" + digest)
    assert digest.startswith("----- §8 style digest")
