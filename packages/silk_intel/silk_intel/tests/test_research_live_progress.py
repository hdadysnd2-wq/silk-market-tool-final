"""أقفال التقدّم الحيّ بالتكلفة لـ/research (PR-B).

يغطّي: (١) لقطة التقدّم في silk_storage (دمج، started_at يُضبَط مرّة واحدة)،
(٢) silk_context.snapshot_research_progress (قناة جانبية صامتة، تقرأ العدّاد
القائم بلا عدّاد جديد)، (٣) write_reviewed_report(on_stage=...) يُصدر
"writer"/"reviewer" بالترتيب الصحيح، (٤) GET /research/{id}/status يعكس
المرحلة/الزمن المنقضي/النداءات/التكلفة حتى الاكتمال عبر تشغيلة خلفية حقيقية
(هيرمتية)، بما فيها علَم الصدق لنموذج غير مُسعَّر، (٥) الواجهة تعرض التكلفة
دوماً بعلامة "~" وتُظهر التكلفة النهائية في بطاقة اقتصاد البيانات.

هيرمتي بالكامل — لا شبكة، لا مفتاح حقيقي.
Run:  python3 -m pytest tests/test_research_live_progress.py -q
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# التسلسل المعياري لمراحل /research (يطابق api.py:_STAGE_LABEL_AR) — يُستعمَل
# لفحص عدم-التنازل بدل اشتراط رؤية "missions" أوّلاً (راجع التعليق عند نقطة
# الاستعمال لسبب السباق المشروع).
# الترتيب الزمني الحقيقي لمراحل التقدّم كما تبثّها المصادر (مصدر الحقيقة:
# silk_missions.py:387 «missions» ← api.py:1149 «analyst» ← api.py:1191
# «enrich_leads» ← on_stage «writer»/«reviewer» ← api.py:1254 «done»).
# البند ١٥ (أمر العمل): «enrich_leads» كانت مبثوثةً فعليًا لكنها غائبة من هذه
# القائمة، فأيّ استطلاعٍ يرصدها كان يرفع ValueError (فشلٌ متقطّع حسب التوقيت).
# الإصلاح الصحيح: إكمال القائمة لتطابق المصدر — لا إضعاف حارس الترتيب.
_STAGE_ORDER = ["missions", "analyst", "enrich_leads", "writer",
                "reviewer", "done"]


def _client():
    from fastapi.testclient import TestClient
    import api
    return TestClient(api.app)


# ═══ ١ — silk_storage: لقطة التقدّم (دمج، started_at يُضبَط مرّة واحدة) ═════

def test_progress_snapshot_merges_and_locks_started_at_once():
    import silk_storage
    db = os.path.join(tempfile.mkdtemp(), "silk.db")
    aid = silk_storage.create_research_run("تمور", "NLD", "080410", {}, path=db)

    silk_storage.update_research_progress(
        aid, path=db, stage="missions", started_at="2026-07-15T10:00:00",
        llm_calls=3, tool_calls=5, cost_usd_estimate=0.02)
    got = silk_storage.get_research_progress(aid, path=db)
    assert got["stage"] == "missions" and got["llm_calls"] == 3
    assert got["started_at"] == "2026-07-15T10:00:00"

    # لقطة لاحقة: started_at لا يتحرّك حتى لو أُعيد تمريره؛ الحقول الأخرى تُحدَّث.
    silk_storage.update_research_progress(
        aid, path=db, stage="writer", started_at="2026-07-15T11:00:00",
        llm_calls=20, tool_calls=40, cost_usd_estimate=0.5)
    got2 = silk_storage.get_research_progress(aid, path=db)
    assert got2["stage"] == "writer" and got2["llm_calls"] == 20
    assert got2["started_at"] == "2026-07-15T10:00:00"          # لم يتغيّر


def test_progress_none_fields_are_ignored_not_overwritten():
    import silk_storage
    db = os.path.join(tempfile.mkdtemp(), "silk.db")
    aid = silk_storage.create_research_run("تمور", "NLD", "080410", {}, path=db)
    silk_storage.update_research_progress(aid, path=db, stage="analyst",
                                          llm_calls=7)
    silk_storage.update_research_progress(aid, path=db, stage="writer",
                                          llm_calls=None)   # لا يمسح llm_calls
    got = silk_storage.get_research_progress(aid, path=db)
    assert got["stage"] == "writer" and got["llm_calls"] == 7


def test_progress_defaults_to_empty_dict_for_unknown_or_missing():
    import silk_storage
    db = os.path.join(tempfile.mkdtemp(), "silk.db")
    assert silk_storage.get_research_progress(999999, path=db) == {}


# ═══ ٢ — silk_context.snapshot_research_progress: قناة جانبية صامتة ════════

def test_snapshot_is_noop_without_analysis_id():
    import silk_context
    silk_context.snapshot_research_progress(None, "missions")  # لا استثناء، لا شيء يُكتب


def test_snapshot_reads_existing_counter_no_new_counter():
    import silk_context
    import silk_storage
    db = os.path.join(tempfile.mkdtemp(), "silk.db")
    aid = silk_storage.create_research_run("تمور", "NLD", "080410", {}, path=db)
    with patch("silk_storage._db_path", return_value=db):
        silk_context.begin_data_counter()
        silk_context.count_data("llm_calls", 4)
        silk_context.count_data("tool_calls", 9)
        silk_context.record_llm_usage("claude-opus-4-8", 1000, 500)
        silk_context.snapshot_research_progress(aid, "missions", started_at="x")
    got = silk_storage.get_research_progress(aid, path=db)
    assert got["llm_calls"] == 4 and got["tool_calls"] == 9
    assert got["cost_usd_estimate"] > 0                 # من نفس estimate_cost_usd
    assert got["cost_unpriced_models"] == []


def test_snapshot_flags_unpriced_model_never_fabricates_zero():
    import silk_context
    import silk_storage
    db = os.path.join(tempfile.mkdtemp(), "silk.db")
    aid = silk_storage.create_research_run("تمور", "NLD", "080410", {}, path=db)
    with patch("silk_storage._db_path", return_value=db):
        silk_context.begin_data_counter()
        silk_context.record_llm_usage("some-future-model-2099", 1000, 500)
        silk_context.snapshot_research_progress(aid, "writer")
    got = silk_storage.get_research_progress(aid, path=db)
    assert "some-future-model-2099" in got["cost_unpriced_models"]  # علَم صدق صريح


def test_snapshot_write_failure_does_not_raise():
    import silk_context
    with patch("silk_storage.update_research_progress",
              side_effect=RuntimeError("disk full")):
        silk_context.begin_data_counter()
        silk_context.snapshot_research_progress(1, "missions")  # لا يُسقِط التشغيلة


# ═══ ٣ — write_reviewed_report(on_stage=...): تسلسل writer→reviewer ═══════

def test_write_reviewed_report_emits_writer_then_reviewer_in_order():
    import silk_ai_judge as aj
    stages: list[str] = []

    def fake_call(system, user, max_tokens=1600, model=None, timeout=None):
        return "## 1. الخلاصة\nتقرير كامل بلا اقتطاع."

    def fake_review(draft, mission_reports, trace_id=None):
        return {"approved": True, "issues": []}

    with patch("silk_ai_judge._call", side_effect=fake_call), \
         patch("silk_ai_judge.review_report", side_effect=fake_review), \
         patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k"}):
        out = aj.write_reviewed_report(
            {}, "ملخّص", {"verdict": "WATCH"}, "تمور", "Netherlands",
            on_stage=lambda s: stages.append(s))
    assert out["report"]
    assert stages == ["writer", "reviewer"]      # مسوّدة واحدة، اعتماد فوري


def test_write_reviewed_report_emits_reviewer_then_writer_on_revision_cycle():
    import silk_ai_judge as aj
    stages: list[str] = []
    calls = {"n": 0}

    def fake_call(system, user, max_tokens=1600, model=None, timeout=None):
        calls["n"] += 1
        return f"## 1. الخلاصة\nمسوّدة رقم {calls['n']}."

    # PART C1: التنقيح يتطلّب مشكلة حاجبة صراحةً — بدونها لا دورة ثانية.
    reviews = iter([{"approved": False, "issues": ["أضف السعر"],
                     "blocking": ["أضف السعر"]},
                    {"approved": True, "issues": []}])

    def fake_review(draft, mission_reports, trace_id=None):
        return next(reviews)

    with patch("silk_ai_judge._call", side_effect=fake_call), \
         patch("silk_ai_judge.review_report", side_effect=fake_review), \
         patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k"}):
        out = aj.write_reviewed_report(
            {}, "ملخّص", {"verdict": "WATCH"}, "تمور", "Netherlands",
            max_cycles=2, on_stage=lambda s: stages.append(s))
    assert out["review_cycles"] == 2
    assert stages == ["writer", "reviewer", "writer", "reviewer"]


def test_on_stage_callback_exception_does_not_break_writer():
    import silk_ai_judge as aj

    def fake_call(system, user, max_tokens=1600, model=None, timeout=None):
        return "## 1. الخلاصة\nتقرير."

    def fake_review(draft, mission_reports, trace_id=None):
        return {"approved": True, "issues": []}

    def boom(s):
        raise RuntimeError("frontend hook exploded")

    with patch("silk_ai_judge._call", side_effect=fake_call), \
         patch("silk_ai_judge.review_report", side_effect=fake_review), \
         patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k"}):
        out = aj.write_reviewed_report(
            {}, "ملخّص", {"verdict": "WATCH"}, "تمور", "Netherlands",
            on_stage=boom)
    assert out["report"]                          # لم يُسقَط رغم فشل on_stage


# ═══ ٤ — GET /research/{id}/status عبر تشغيلة خلفية حقيقية (هيرمتية) ═══════

def _fake_call_tools_factory(log_list=None):
    def fake_call_tools(system, messages, tools=None, max_tokens=1600,
                        model=None, timeout=None):
        if log_list is not None:
            log_list.append(system[:60])
        return {"stop_reason": "end_turn", "content": [
            {"type": "text", "text": json.dumps(
                {"findings": [], "gaps": [], "summary": "ok"})}],
            "usage": {"input_tokens": 100, "output_tokens": 50}}
    return fake_call_tools


def _fake_call(system, user, max_tokens=1600, model=None, timeout=None):
    return json.dumps({"verdict": "WATCH", "confidence": 0.5, "reasoning": "ok"})


def _fake_call_writer(system, user, max_tokens=1600, model=None, timeout=None):
    return "## 1. الخلاصة التنفيذية\nتقرير تجريبي كامل."


def test_status_endpoint_reflects_stage_elapsed_calls_and_cost_end_to_end():
    tool_calls: list[str] = []
    fake_call_tools = _fake_call_tools_factory(tool_calls)
    db = os.path.join(tempfile.mkdtemp(), "silk.db")
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test",
                                 "SILK_API_KEY": "secret"}), \
         patch("silk_llm_runtime._call_tools", side_effect=fake_call_tools), \
         patch("silk_synthesis._call", side_effect=_fake_call), \
         patch("silk_ai_judge._call", side_effect=_fake_call_writer), \
         patch("silk_storage._db_path", return_value=db):
        client = _client()
        hdr = {"X-API-Key": "secret"}

        r = client.post("/research", headers=hdr, json={
            "product": "تمور", "market": "Nigeria", "hs_code": "080410",
            "persist": True, "async_run": True})
        assert r.status_code == 202
        analysis_id = r.json()["analysis_id"]

        seen_stages: list[str] = []
        status = None
        for _ in range(400):
            sr = client.get(f"/research/{analysis_id}/status", headers=hdr)
            assert sr.status_code == 200
            status = sr.json()
            if status.get("stage") and (not seen_stages or
                                        seen_stages[-1] != status["stage"]):
                seen_stages.append(status["stage"])
            if status["status"] != "running":
                break
            time.sleep(0.01)
        assert status["status"] == "completed"

        # مراحل مرصودة بترتيب زمني صحيح — لا نشترط رؤية كل مرحلة فرادى (استطلاع
        # قد يفوّت مرحلة قصيرة)، ولا نشترط أن تكون الأولى "missions" تحديداً:
        # تشغيلة اختبار مُصطنَعة (نداءات كلود مُموَّهة شبه فورية) قد تكتمل بين
        # نداء POST /research وأول GET status، فيكون أول رصد "done" مباشرة —
        # سباق حقيقي لا عطلاً؛ عتبة عدم-التنازل تُبقي حراسة الترتيب فعلية (لا
        # إضعاف الحارس، راجع silk-operations §THE RULES.٥) بينما تقبل هذا السباق
        # المشروع. الأخيرة تبقى "done" دوماً — تلك الضمانة لا تتزحزح.
        assert seen_stages, "لم تُرصد أي مرحلة إطلاقاً"
        indices = [_STAGE_ORDER.index(s) for s in seen_stages]
        assert indices == sorted(indices), (
            f"stages observed out of canonical order: {seen_stages}")
        assert seen_stages[-1] == "done"

        # الحقول الحيّة كلها ظهرت خلال الاستطلاع لا None طوال الوقت.
        assert status["elapsed_seconds"] is not None
        assert status["llm_calls"] is not None and status["llm_calls"] > 0
        assert status["cost_usd_estimate"] is not None
        assert status["cost_usd_estimate"] >= 0
        assert status["stage_label"] == "اكتمل"          # تسمية عربية للمرحلة النهائية


def test_stage_order_check_still_catches_a_genuine_regression():
    """تخفيف الاختبار السابق (قبول أول رصد ≠ "missions") لا يُضعِف حراسة
    الترتيب — تسلسل حقيقي مقلوب أو متذبذب لا يزال يُسقِط الفحص (silk-operations
    §THE RULES.٥: لا إضعاف حارس لإسكاته)."""
    def check(seen_stages):
        indices = [_STAGE_ORDER.index(s) for s in seen_stages]
        assert indices == sorted(indices)

    check(["missions", "done"])            # سباق مقبول: مرحلة مفقودة، ترتيب سليم
    check(["done"])                        # سباق متطرّف مقبول: رُصد الاكتمال فقط
    with pytest.raises(AssertionError):
        check(["analyst", "missions", "done"])   # تراجُع حقيقي: عاد لمرحلة أسبق
    with pytest.raises(AssertionError):
        check(["writer", "reviewer", "writer", "done"])  # تذبذب حقيقي


def test_status_endpoint_stage_is_none_before_any_snapshot():
    """قبل أي لقطة تقدّم (مثال: تشغيلة أُنشئت للتوّ) — stage=None صريح لا قيمة مُختلَقة."""
    import silk_storage
    db = os.path.join(tempfile.mkdtemp(), "silk.db")
    aid = silk_storage.create_research_run("تمور", "NLD", "080410", {}, path=db)
    with patch.dict(os.environ, {"SILK_API_KEY": "secret"}), \
         patch("silk_storage._db_path", return_value=db):
        r = _client().get(f"/research/{aid}/status", headers={"X-API-Key": "secret"})
    assert r.status_code == 200
    body = r.json()
    assert body["stage"] is None and body["stage_label"] is None
    assert body["elapsed_seconds"] is None


# ═══ ٥ — الواجهة: علامة "~" دوماً + بطاقة اقتصاد البيانات النهائية ══════════

def _html():
    path = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "web", "index.html")
    return open(path, encoding="utf-8").read()


def test_frontend_progress_text_always_prefixes_cost_with_tilde():
    html = _html()
    assert "function researchProgressText" in html
    assert "~$" in html                            # كل عرض تكلفة تقديري = علامة "~"


def test_frontend_shows_unpriced_model_honesty_flag():
    html = _html()
    assert "cost_unpriced_models" in html
    assert "⚠" in html


def test_frontend_data_economics_card_renders_final_cost():
    html = _html()
    assert "التكلفة الفعلية المُقدَّرة" in html
    assert "cost_usd_estimate" in html
