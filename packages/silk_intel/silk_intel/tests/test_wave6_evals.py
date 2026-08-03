"""اختبارات الموجة ٥ (V5): أداة تقييم البحث العميق (silk_evals).

يغطي: المحور البرمجي (استشهاد الأرقام — رقم مختلَق واحد = صفر فوري)، عزل
أرقام ترقيم العناوين عن الفحص، تصنيف الحالات الذهبية (مخطط، رفض الفاسدة)،
منطق التراجع (>10 نقطة = فشل)، evaluate_report بلا مفتاح = محاور كلود
غائبة بفجوة معلنة لا محذوفة، وأن golden_cases.json الحالي فارغ بصدق (لا
أرقام مُختلَقة). لا شبكة ولا مفتاح مطلوبان لأي اختبار هنا.
Run:  python3 -m pytest tests/ -q
"""
import json
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _mission_reports(claim="الاستيراد بلغ 950,000 دولار في 2023"):
    from silk_agents import AgentReport
    from silk_data_layer import DataPoint
    return {"trade_flow": AgentReport(
        "LLMAgent:trade_flow", [DataPoint(claim, "x", 0.9, "مبني على: n")],
        False, "ok")}


def test_citation_axis_zero_for_a_number_absent_from_datapoints():
    import silk_evals as ev

    bad_report = "## 1. الخلاصة\nبلغ الاستيراد 12,345,678 دولار."
    out = ev.citation_correctness_score(bad_report, _mission_reports())
    assert out["score"] == 0
    assert 12345678.0 in out["violations"]


def test_citation_axis_passes_when_every_number_is_grounded():
    import silk_evals as ev

    good_report = "## 1. الخلاصة\nبلغ الاستيراد 950,000 دولار."
    out = ev.citation_correctness_score(good_report, _mission_reports())
    assert out["score"] == 100
    assert out["violations"] == []


def test_section_header_numbering_is_not_treated_as_a_claim():
    import silk_evals as ev

    # "## 15. ..." رقم قسم لا ادّعاء — لا يجوز أن يُسقط الاستشهاد بلا سبب.
    report = "## 15. ملحق المصادر والثقة\nبلغ الاستيراد 950,000 دولار."
    out = ev.citation_correctness_score(report, _mission_reports())
    assert out["score"] == 100
    assert 15.0 not in _extract(ev, report)


def _extract(ev, text):
    return ev._extract_numbers(text)


def test_golden_case_validation_rejects_incomplete_case():
    import silk_evals as ev

    errors = ev.validate_case({"key": "x"})
    assert "missing field: product" in errors
    # WS10: `expected` صار اختيارياً — حالةٌ بلا `expected` **ولا** `structural`
    # مرفوضة (بلا معيار قبول)؛ حالةٌ بنيوية بحتة مقبولة.
    assert any("expected" in e and "structural" in e for e in errors)


def test_golden_case_validation_accepts_well_formed_case():
    import silk_evals as ev

    case = {"key": "nigeria_dates", "product": "تمور", "market": "نيجيريا",
           "hs_code": "080410",
           "expected": {"trade_import_usd": {
               "value": 950000, "year": 2023,
               "source_url": "https://comtradeplus.un.org/x"}},
           "verified_at": "2026-01-01", "verified_by": "reviewer-name"}
    assert ev.validate_case(case) == []


def test_golden_case_validation_rejects_bad_hs_code():
    import silk_evals as ev

    case = {"key": "x", "product": "p", "market": "m", "hs_code": "80410",
           "expected": {}, "verified_at": "2026-01-01", "verified_by": "me"}
    errors = ev.validate_case(case)
    assert any("hs_code" in e for e in errors)


def test_load_golden_cases_skips_invalid_rows_without_crashing(tmp_path):
    import silk_evals as ev

    path = tmp_path / "cases.json"
    path.write_text(json.dumps([
        {"key": "bad"},  # ناقص — يُرفض
        {"key": "good", "product": "تمور", "market": "نيجيريا",
         "hs_code": "080410", "expected": {},
         "verified_at": "2026-01-01", "verified_by": "me"},
    ], ensure_ascii=False), encoding="utf-8")
    cases = ev.load_golden_cases(str(path))
    assert len(cases) == 1
    assert cases[0]["key"] == "good"


def test_committed_golden_cases_file_has_structural_case_no_fabricated_numbers():
    # WS10 (إغلاق الفجوة النظامية): الملف لم يعد فارغاً — يحمل الحالة القياسية
    # (قطر × 200811) بوّابةً **بنيوية** هرمتية. عقد عدم الاختلاق محفوظ: لا رقم
    # مرجعيّ (`expected`) مُختلَق بلا مصدرٍ محقَّق — أيّ حالة تحمل `expected`
    # يجب أن يكون كل صفٍّ فيه بـ source_url حقيقي (يُفحَص بـ validate_case).
    import silk_evals as ev

    cases = ev.load_golden_cases()          # يرفض أيّ حالة فاسدة الشكل
    assert cases, "الحالة القياسية يجب أن تُحمَّل (الفجوة النظامية مُغلقة)"
    qatar = next((c for c in cases if c["key"] == "qatar_peanut_butter"), None)
    assert qatar is not None and "structural" in qatar
    # لا أرقام مُختلَقة: هذه الحالة بنيوية بحتة (بلا `expected`) — أو، إن أُضيف
    # `expected` لاحقاً، فبـ source_url حقيقي (يفرضه validate_case، أعلاه).
    assert "expected" not in qatar


def test_regression_detected_when_score_drops_more_than_threshold():
    import silk_evals as ev

    cmp = ev.compare_to_last_score("nigeria_tea", 70, {"nigeria_tea": 85})
    assert cmp["regression"] is True
    assert cmp["drop"] == 15


def test_no_regression_for_small_drop_or_first_run():
    import silk_evals as ev

    small = ev.compare_to_last_score("k", 80, {"k": 85})
    assert small["regression"] is False
    first = ev.compare_to_last_score("k", 80, {})
    assert first["regression"] is False
    assert first["previous"] is None


def test_evaluate_report_without_key_still_computes_citation_axis():
    import silk_evals as ev

    saved = os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        result = {"deep_research": {
            "missions": _mission_reports(),
            "report": {"report": "## 1. الخلاصة\nالاستيراد 950,000 دولار."}}}
        out = ev.evaluate_report(result)
    finally:
        if saved is not None:
            os.environ["ANTHROPIC_API_KEY"] = saved
    assert out["axes"]["citation_correctness"] == 100
    assert out["axes"]["section_completeness"] is None  # فجوة معلنة لا محذوفة
    assert out["grounded_axes"] == ["citation_correctness"]
    assert "بلا مفتاح" in out["note"]


def test_evaluate_report_zero_citation_drags_overall_down_but_not_to_none():
    import silk_evals as ev

    def fake_call(system, user, max_tokens=1600, model=None, timeout=None):
        return json.dumps({"section_completeness": 90, "gaps_declared": 90,
                           "recommendation_grounded": 90,
                           "intersections_quality": 90, "reasoning": "x"})

    result = {"deep_research": {
        "missions": _mission_reports(),
        "report": {"report": "## 1. الخلاصة\nرقم مختلق 99999999."}}}
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test"}), \
         patch("silk_ai_judge._call", side_effect=fake_call):
        out = ev.evaluate_report(result)
    assert out["axes"]["citation_correctness"] == 0
    assert out["citation_violations"] == [99999999.0]
    # المحور المزيَّف بصفر يجذب الإجمالي دون الأصفار الأخرى (٩٠) بوضوح.
    assert out["overall"] < 90


def test_run_case_and_main_are_not_exercised_live_but_wired(monkeypatch):
    # لا تشغيل حي هنا (يتطلب شبكة+مفتاح) — تحقّق بنيوي فقط: main() يعالج
    # مفتاح حالة غير معروف بأدب (لا استثناء) حين القائمة فارغة.
    import silk_evals as ev

    rc = ev.main(["--case", "nonexistent_case"])
    assert rc == 1
