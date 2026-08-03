"""اختبارات إصلاحات مراجعة Stage 5 — الثغرات الثلاث + حارس البرهان.

1) حكم واحد لا حكمان: قرار §8 هو الحكم الوحيد في الخلاصة والخاتمة وكل مشتق.
2) عنوان بحث ويب ليس اسم كيان: يُعرض «مرجع للمراجعة اليدوية» حصراً.
3) حقائق Google Trends تُحسب لقسم الاتجاه (كانت «الاتجاه 0/0»).
4) أثر برهاني (MagicMock/example.org) في تشغيلة إنتاجية = رفض التوليد؛
   والتشغيلة الموسومة SILK_HERMETIC تحمل لافتة TEST RUN ظاهرة.
"""
import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conftest import block_network  # noqa: E402

import silk_store  # noqa: E402


def _seed_store():
    silk_store.migrate()
    silk_store.upsert_trade_flows([
        {"hs6": "080410", "reporter_iso3": "CHN", "partner_iso3": "WLD",
         "year": 2021, "flow": "M", "value_usd": 4.0e7},
        {"hs6": "080410", "reporter_iso3": "CHN", "partner_iso3": "WLD",
         "year": 2023, "flow": "M", "value_usd": 6.0e7, "qty_kg": 2.0e7},
        {"hs6": "080410", "reporter_iso3": "CHN", "partner_iso3": "SAU",
         "year": 2023, "flow": "M", "value_usd": 1.8e7, "qty_kg": 8.0e6},
        {"hs6": "080410", "reporter_iso3": "CHN", "partner_iso3": "IRN",
         "year": 2023, "flow": "M", "value_usd": 3.0e7}])


def test_single_authoritative_verdict_everywhere():
    """حكم الجورية يخالف حكم §8 والتقرير يحمل حكم §8 وحده في الخلاصة والخاتمة
    والنص، والجورية سطر كفاية فقط. (كانت الجورية NO-GO لأن الوكلاء الأساسيين
    عميان عن المخزن؛ منذ التوجيه عبر المخزن أولاً يقرؤون البذرة فتصير
    PRELIMINARY/ناقصة — الثابت المُختبَر أن حكمها ليس الحكم المنشور.)"""
    _seed_store()
    import silk_engine
    from silk_render import build_view, render_text
    from silk_reports import render_brief, render_markdown
    with block_network():
        res = silk_engine.analyze("تمور",
                                  countries=[{"iso3": "CHN", "m49": "156"}],
                                  year=2023, with_research=True)
    jury = res["markets"][0]["jury"]
    ed = res["markets"][0]["decision"]
    assert ("NO-GO" in jury["verdict"] or "INCONCLUSIVE" in jury["verdict"])
    assert jury["verdict"] != ed["verdict"] and ed["verdict"] == "CONDITIONAL-GO"
    view = build_view(res)
    # الحكم الموحّد في النموذج نفسه — كل المشتقات ترثه بنيوياً.
    assert view["decision"]["verdict"] == ed["verdict"]
    assert "كفاية البيانات" in view["decision"]["sufficiency"]
    # تشغيلة نظيفة (مخزن مبذور + قطع شبكة صادق) تمرّ من حارس الإنتاج كما هي.
    md = render_markdown(view)
    txt = render_text(view)
    brief = render_brief(view)
    # سدّ تسريب: كل المشتقات (md/txt/brief) تحمل الآن الترجمة العربية
    # الواحدة لنفس الحكم — لا رمز آلة CONDITIONAL-GO خام في أي منها (كان
    # md/txt وحدهما يطبعان الرمز الخام قبل هذا الإصلاح؛ حكم واحد بمصدر
    # عرض واحد silk_narrative.verdict_ar، لا حكمان بصياغتين).
    for out in (md, txt, brief):
        assert "دخول مشروط" in out         # ترجمة CONDITIONAL-GO الواحدة
        assert "CONDITIONAL-GO" not in out
        assert "NO-GO" not in out          # لا حكم ثانٍ في أي قسم
    # وأول سطر قرار في الخاتمة = نفس الحكم (سطور المختصر تشتق من decision).
    assert "دخول مشروط" in view["brief"][0]


def test_search_titles_are_references_never_entity_names():
    import silk_research as R
    from silk_data_layer import DataPoint, _today
    web = [DataPoint({"title": "top تمور brands manufacturers — تقرير 2024",
                      "snippet": "x", "link": "https://site.example/page"},
                     "Web Search (Serper)", 0.5, "organic", _today())]
    maps = [DataPoint({"name": "شركة التمور الذهبية للتجارة",
                       "address": "شارع 1", "rating": 4.2},
                      "Google Maps", 0.7, "place", _today())]
    with mock.patch("silk_websearch_agent.web_search", return_value=web), \
         mock.patch("silk_maps_agent.find_places", return_value=maps):
        out, _refs, _dropped = R._entities_and_references(["q"], "mq")
    kinds = {e["kind"] for e in out}
    assert kinds == {"entity", "reference"}
    ref = next(e for e in out if e["kind"] == "reference")
    assert "title" in ref and "name" not in ref       # لا يُخزَّن العنوان كاسم
    # المولّد يطبع المرجع بوسمه الصريح — أبداً ليس منافساً بالاسم.
    from silk_reports import _entry_text, _split_candidates
    assert _entry_text(ref).startswith("مرجع للمراجعة اليدوية:")
    ent = next(e for e in out if e["kind"] == "entity")
    assert not _entry_text(ent).startswith("مرجع")
    # توافُق خلفي: بنود قديمة بلا kind من بحث الويب تُعامل مراجع.
    ents, refs = _split_candidates([{"name": "عنوان قديم", "via": "Serper"},
                                    {"name": "مكان", "via": "Google Maps"}])
    assert len(ents) == 1 and len(refs) == 1


def test_trends_facts_count_toward_trend_section():
    from silk_render import _section_coverage, _section_status
    row = {"components": {},
           "trends": [{"value": 72.0, "source": "Google Trends",
                       "confidence": 0.7, "note": "mean interest"}],
           "trend": {"source": "UN Comtrade",
                     "series": [{"year": 2021, "value": 4.0e7},
                                {"year": 2022, "value": None},
                                {"year": 2023, "value": 6.0e7}]}}
    cov = _section_coverage(row)["trend"]
    assert cov["attempted"] == 4            # ٣ سنوات خط + إشارة Trends
    assert cov["contributed"] == 3          # سنتان مرصودتان + Trends
    st = _section_status(row)["trend"]
    assert st["status"] == "ok" and "Google Trends" in st["sources_attempted"]
    # وبلا أي حقيقة اتجاه: القسم 0/0 يبقى صادقاً لا صامتاً.
    empty = _section_coverage({"components": {}})["trend"]
    assert empty == {"attempted": 0, "contributed": 0, "score": 0.0,
                     "single_source": False, "low_confidence": True}


def test_hermetic_artifacts_blocked_in_production_and_bannered_in_test():
    from silk_reports import render_markdown
    poisoned = {"product": "تمور", "hs_code": "080410", "classified": True,
                "header": {}, "decision": {"verdict": "GO"}, "markets": [
                    {"country": "China", "section_status": {},
                     "section_coverage": {}, "components_detail": [],
                     "swot": {"S": [], "W": [], "O": [], "T": []},
                     "named_competitors": ["x — https://example.org/a"]}],
                "competitive_position": {}, "brief": [], "limits": [],
                "provenance": []}
    os.environ.pop("SILK_HERMETIC", None)
    with pytest.raises(RuntimeError, match="example.org"):
        render_markdown(poisoned)
    # نفس النموذج موسوماً SILK_HERMETIC: يمرّ ويحمل لافتة TEST RUN الظاهرة.
    os.environ["SILK_HERMETIC"] = "1"
    try:
        poisoned["test_run"] = True
        md = render_markdown(poisoned)
        assert "TEST RUN" in md.splitlines()[0]
    finally:
        os.environ.pop("SILK_HERMETIC", None)
    # والعرض الإنتاجي النظيف (بلا آثار برهانية) يمرّ من الحارس دون اعتراض.
    clean = dict(poisoned)
    clean.pop("test_run", None)
    clean["markets"] = [dict(poisoned["markets"][0], named_competitors=[])]
    assert "سِلك" in render_markdown(clean)
    # وbuild_view يرفع الراية من البيئة.
    from silk_render import build_view
    os.environ["SILK_HERMETIC"] = "1"
    try:
        assert build_view({"markets": []})["test_run"] is True
    finally:
        os.environ.pop("SILK_HERMETIC", None)
    assert build_view({"markets": []})["test_run"] is False


def test_entry_decision_confidence_is_phrase_not_raw_number():
    """ثقة قرار الدخول (§8) كانت تُطبع رقماً عشرياً خاماً (ثقة: 0.52) في كلا
    الصيغتين — يجب أن تظهر بصيغة بشرية (confidence_phrase) بدلاً منه."""
    import re
    _seed_store()
    import silk_engine
    from silk_render import build_view
    from silk_reports import render_markdown
    with block_network():
        res = silk_engine.analyze("تمور",
                                  countries=[{"iso3": "CHN", "m49": "156"}],
                                  year=2023, with_research=True)
    view = build_view(res)
    ed = view["markets"][0]["entry_decision"]
    assert ed.get("confidence") is not None
    md = render_markdown(view)
    assert not re.search(r"الثقة:\s*0\.\d", md), "raw entry-decision confidence leaked"
    assert any(b in md for b in ("عالية (", "متوسطة (", "منخفضة ("))
    pytest.importorskip("docx")
    import os as _os
    import tempfile as _tempfile
    from conftest import docx_all_text
    from silk_reports import render_docx
    path = render_docx(view, _os.path.join(_tempfile.mkdtemp(), "r.docx"))
    texts = docx_all_text(path)
    assert not re.search(r"الثقة:\s*0\.\d", texts)
