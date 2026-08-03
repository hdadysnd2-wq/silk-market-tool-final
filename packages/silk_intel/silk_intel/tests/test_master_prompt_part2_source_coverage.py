"""Master Prompt Part 2 §D — تغطية المصادر ووسم «تقدير استرشادي».

عتبة القبول ≥٨٥٪ من المؤشرات (DataPoint بقيمة فعلية) بمصدرٍ مسمّى حقيقي أو
وسم «تقدير استرشادي» صريح؛ دون العتبة يجب أن يُفشِل الحكم بدل الشحن الصامت
(البند ٩، «73 من 98 غير مصدَّرة»، مُعاد إنتاجه هنا بنسبةٍ مصغَّرة).

Run: python3 -m pytest tests/test_master_prompt_part2_source_coverage.py -q
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.canonical_kuwait_peanut_butter import kuwait_research_blob  # noqa: E402


def _finding(value, source="", note=""):
    return {"value": value, "source": source, "confidence": 0.7, "note": note,
            "retrieved_at": "2026-07-20", "status": ""}


def _dr_with_findings(findings: list[dict]) -> dict:
    return {"missions": {"m": {"agent_name": "LLMMissionAgent",
                               "summary": "ok", "failed": False,
                               "findings": findings}},
            "report": {"text": "## 1. الخلاصة التنفيذية\nنص."}}


def test_below_85pct_coverage_fails():
    """٥ مؤشرات، مصدرٌ واحد فقط مسمّى (20%) — دون العتبة، يجب أن يُفشِل."""
    from silk_quality_gate import _check_source_coverage
    dr = _dr_with_findings([
        _finding(1, source="UN Comtrade"),
        _finding(2, source=""), _finding(3, source="—"),
        _finding(4, source=None), _finding(5, source="-")])
    findings = _check_source_coverage(dr)
    assert findings, "تغطية 20% كان يجب أن تُفشِل"
    assert findings[0]["check"] == "source_coverage_below_threshold"
    assert findings[0]["repairable"] is False


def test_below_85pct_coverage_fails_the_full_quality_gate():
    from silk_quality_gate import run_quality_gate, FAIL
    dr = _dr_with_findings([
        _finding(1, source="UN Comtrade"),
        _finding(2, source=""), _finding(3, source="—"),
        _finding(4, source=None), _finding(5, source="-")])
    out = run_quality_gate({"deep_research": dr})
    assert out["verdict"] == FAIL
    assert any(f["check"] == "source_coverage_below_threshold"
              for f in out["findings"])


def test_indicative_estimate_tag_counts_as_backed():
    """رقمٌ بلا مصدرٍ مسمّى لكن موسومٌ صراحةً «تقدير استرشادي» في الملاحظة
    يُحتسَب مغطّى — لا يُعامَل كـ«—» عارية."""
    from silk_source_coverage import INDICATIVE_ESTIMATE_TAG
    from silk_quality_gate import _check_source_coverage
    dr = _dr_with_findings([
        _finding(1, source="UN Comtrade"),
        _finding(2, source="", note=f"{INDICATIVE_ESTIMATE_TAG} — مشتقّ من "
                                     "متوسط الفئة المجاورة، لا رصدٌ مباشر")])
    assert _check_source_coverage(dr) == []


def test_declared_gaps_excluded_from_denominator():
    """فجوةٌ معلنة (value=None) ليست مؤشراً مُسلَّماً — لا تُحتسَب في المقام
    ولا تُنقِص التغطية زوراً."""
    from silk_quality_gate import _check_source_coverage
    dr = _dr_with_findings([
        _finding(1, source="UN Comtrade"),
        _finding(None, source="", note="fetch_failed")])
    assert _check_source_coverage(dr) == []


def test_kuwait_canonical_fixture_meets_85pct_threshold():
    """المدوّنة القانونية (الكويت) — كل مؤشراتها الفعلية تحمل مصدراً مسمّى
    حقيقياً (UN Comtrade/World Bank/Google Maps)؛ يجب أن تتجاوز العتبة."""
    import silk_render as R
    from silk_source_coverage import compute_source_coverage, SOURCE_COVERAGE_MIN_PCT
    dr = R.build_view(kuwait_research_blob())["deep_research"]
    cov = compute_source_coverage(dr)
    assert cov["pct"] >= SOURCE_COVERAGE_MIN_PCT, cov


def test_default_sources_defined_for_all_four_product_families():
    """قوائم المصادر الافتراضية مُعرَّفة للأربع عائلات (غذاء/نسيج/كيماويات/
    آلات)، كلٌّ منها بمصدرٍ حقيقيٍّ مسمّى ورابط — البند ١٠."""
    from silk_source_coverage import default_sources_for_family, known_product_families
    families = known_product_families()
    for fam in ("food", "textiles", "chemicals", "machinery"):
        assert fam in families
        rows = default_sources_for_family(fam)
        assert len(rows) >= 3, f"{fam}: يحتاج ≥3 مصادر افتراضية"
        for row in rows:
            assert row["source_name"] and row["url"].startswith("http")


def test_tag_indicative_estimate_helper_shape():
    from silk_source_coverage import tag_indicative_estimate, INDICATIVE_ESTIMATE_TAG
    out = tag_indicative_estimate("290-380 دولار", "متوسط ثلاث نقاط سعرٍ مرصودة يدوياً")
    assert INDICATIVE_ESTIMATE_TAG in out
    assert "290-380 دولار" in out
    assert "متوسط ثلاث نقاط سعرٍ مرصودة يدوياً" in out
