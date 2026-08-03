"""اختبارات الموجة ٤أ (V5): كاتب التقرير + المراجع (silk_ai_judge).

يغطي: بلا مفتاح => None لا اختلاق، حلقة الكتابة/المراجعة تتوقف عند
الموافقة، أقصى دورتين مع ملاحظات غير محلولة ظاهرة، وتسجيل reviewer/
report_writer إضافياً في AGENT_CATALOG.
Run:  python3 -m pytest tests/ -q
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _mission_reports():
    from silk_agents import AgentReport
    from silk_data_layer import DataPoint
    return {"trade_flow": AgentReport(
        "LLMAgent:trade_flow",
        [DataPoint(950000.0, "UN Comtrade", 0.9, "استيراد 2023")], False, "ok")}


def _complete_draft():
    """مسوّدة كاملة الأقسام الأحد عشر (الموجة ١٠) — بلا هذا يفشل الفحص
    البنيوي الحتمي في review_report() لأسباب لا علاقة لها بآلية الحلقة
    التي تختبرها هذه الحالات (عدّ الدورات، التوقف عند الموافقة، إلخ)."""
    import silk_ai_judge as aj
    return "\n".join(f"## {i}. {s}\nنص." for i, s in
                     enumerate(aj._REPORT_SECTIONS, 1))


def test_no_key_returns_none_not_fabrication():
    import silk_ai_judge as aj

    saved = os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        out = aj.write_reviewed_report(_mission_reports(), "x",
                                       {"verdict": "WATCH"}, "تمور", "نيجيريا")
        reason = aj.failure_reason()  # نفس السياق (بلا مفتاح) وقت المقارنة
    finally:
        if saved is not None:
            os.environ["ANTHROPIC_API_KEY"] = saved
    assert out == {"report": None, "review_cycles": 0, "unresolved_notes": [],
                   "failure_reason": reason}
    assert "مفتاح" in reason


def test_loop_stops_early_when_reviewer_approves():
    import silk_ai_judge as aj

    calls = {"n": 0}

    def fake_call(system, user, max_tokens=1600, model=None, timeout=None):
        calls["n"] += 1
        if model == aj._FAST_MODEL:
            return '{"issues": [], "approved": true}'
        return _complete_draft()

    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test"}), \
         patch("silk_ai_judge._call", side_effect=fake_call):
        out = aj.write_reviewed_report(_mission_reports(), "x",
                                       {"verdict": "WATCH"}, "تمور", "نيجيريا")

    assert out["review_cycles"] == 1
    assert out["unresolved_notes"] == []
    assert calls["n"] == 2  # كاتب + مراجع، بلا دورة ثانية


def test_default_is_single_cycle_notes_surface_without_revision():
    """PART C1 (انحدار التكلفة $1.6→$2.0): الافتراضي دورة واحدة — المراجع
    يرصد الملاحظات فتُعلَن في «حدود هذا التقرير»، بلا نداء تنقيح إضافي."""
    import silk_ai_judge as aj
    calls = {"writer": 0}

    def fake_call(system, user, max_tokens=1600, model=None, timeout=None):
        if model == aj._FAST_MODEL:
            return '{"issues": ["مشكلة مستمرة"], "blocking": ["مشكلة مستمرة"], "approved": false}'
        calls["writer"] += 1
        return _complete_draft()

    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test"}), \
         patch("silk_ai_judge._call", side_effect=fake_call):
        out = aj.write_reviewed_report(_mission_reports(), "x",
                                       {"verdict": "WATCH"}, "تمور", "نيجيريا")

    assert out["review_cycles"] == 1
    assert out["unresolved_notes"] == ["مشكلة مستمرة"]
    assert out["report"]           # التسليم يحدث رغم الملاحظات غير المحلولة
    assert calls["writer"] == 1    # لا تنقيح — الافتراض دورة واحدة


def test_env_two_cycles_with_blocking_issue_triggers_revision():
    """SILK_MAX_REVIEW_CYCLES=2 + مشكلة حاجبة => دورة تنقيح فعلية."""
    import silk_ai_judge as aj

    def fake_call(system, user, max_tokens=1600, model=None, timeout=None):
        if model == aj._FAST_MODEL:
            return '{"issues": ["رقم بلا سند"], "blocking": ["رقم بلا سند"], "approved": false}'
        return _complete_draft()

    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test",
                                 "SILK_MAX_REVIEW_CYCLES": "2"}), \
         patch("silk_ai_judge._call", side_effect=fake_call):
        out = aj.write_reviewed_report(_mission_reports(), "x",
                                       {"verdict": "WATCH"}, "تمور", "نيجيريا")

    assert out["review_cycles"] == 2
    assert out["unresolved_notes"] == ["رقم بلا سند"]
    assert out["report"]


def test_env_two_cycles_with_only_style_issues_skips_revision():
    """السقف ٢ مفتوح لكن المشاكل غير حاجبة (أسلوبية) => لا نداء تنقيح —
    البوابة توفّر نداء الكاتب الإضافي، والملاحظات تبقى معلَنة."""
    import silk_ai_judge as aj
    calls = {"writer": 0}

    def fake_call(system, user, max_tokens=1600, model=None, timeout=None):
        if model == aj._FAST_MODEL:
            return '{"issues": ["صياغة ركيكة"], "blocking": [], "approved": false}'
        calls["writer"] += 1
        return _complete_draft()

    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test",
                                 "SILK_MAX_REVIEW_CYCLES": "2"}), \
         patch("silk_ai_judge._call", side_effect=fake_call):
        out = aj.write_reviewed_report(_mission_reports(), "x",
                                       {"verdict": "WATCH"}, "تمور", "نيجيريا")

    assert out["review_cycles"] == 1
    assert out["unresolved_notes"] == ["صياغة ركيكة"]
    assert calls["writer"] == 1


def test_max_review_cycles_env_is_clamped_1_to_2():
    import silk_ai_judge as aj
    with patch.dict(os.environ, {"SILK_MAX_REVIEW_CYCLES": "7"}):
        assert aj._max_review_cycles() == 2
    with patch.dict(os.environ, {"SILK_MAX_REVIEW_CYCLES": "0"}):
        assert aj._max_review_cycles() == 1
    with patch.dict(os.environ, {"SILK_MAX_REVIEW_CYCLES": "abc"}):
        assert aj._max_review_cycles() == 1
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("SILK_MAX_REVIEW_CYCLES", None)
        assert aj._max_review_cycles() == 1


def test_reviewer_none_reply_treated_as_no_review_not_rejection():
    import silk_ai_judge as aj

    def fake_call(system, user, max_tokens=1600, model=None, timeout=None):
        return None if model == aj._FAST_MODEL else _complete_draft()

    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test"}), \
         patch("silk_ai_judge._call", side_effect=fake_call):
        out = aj.write_reviewed_report(_mission_reports(), "x",
                                       {"verdict": "WATCH"}, "تمور", "نيجيريا")

    assert out["report"]
    assert out["unresolved_notes"] == []


def test_reviewer_and_writer_registered_additively():
    import silk_ai_judge  # noqa: F401 — يسجّل عند الاستيراد
    import silk_agents

    keys = [a["key"] for a in silk_agents.AGENT_CATALOG]
    assert "reviewer" in keys
    assert "report_writer" in keys
    row = next(a for a in silk_agents.AGENT_CATALOG if a["key"] == "reviewer")
    assert row["paid"] is False
