"""اختبارات وكيل الديناميكيات (P2-8) — أطر مصنّفة بمصادرها، تدهور صادق.

يقفل: بلا مفتاح بحث = فجوة معلنة بلا نداء؛ بلا كلود = إشارات خام معلنة؛
مع كلود = أطر كل نقطة فيها سند وإلا سقطت (نفس انضباط consumer_culture)؛
والقسم ٥ في docx يعرض المصنَّف بأدلته.
Run:  python3 -m pytest tests/test_p2_dynamics_agent.py -q
"""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conftest import block_network  # noqa: E402

from silk_data_layer import DataPoint, _today  # noqa: E402

_ENV_OFF = {"SEARCH_API_KEY": "", "ANTHROPIC_API_KEY": ""}


def test_keyless_declares_gap_without_any_call():
    from silk_dynamics_agent import DynamicsAgent
    with mock.patch.dict(os.environ, _ENV_OFF):
        with block_network():
            rep = DynamicsAgent().run({"product": "تمور", "market": "China"})
    assert rep.failed and rep.findings[0].value is None
    assert "SEARCH_API_KEY" in rep.findings[0].note


def _headlines():
    return [DataPoint({"title": f"عنوان {i} عن سوق التمور والطلب",
                       "link": f"https://x/{i}"},
                      "Web Search (Serper)", 0.5, "organic", _today())
            for i in range(1, 5)]


def test_no_claude_returns_raw_signals_declared_unclassified():
    from silk_dynamics_agent import DynamicsAgent
    with mock.patch.dict(os.environ, {"SEARCH_API_KEY": "k",
                                      "ANTHROPIC_API_KEY": ""}):
        with mock.patch("silk_websearch_agent.web_search",
                        return_value=_headlines()):
            rep = DynamicsAgent().run({"product": "تمور", "market": "China"})
    v = rep.findings[0].value
    assert not rep.failed and v["classified"] is False
    assert len(v["raw_signals"]) >= 1
    assert "كلود" in rep.findings[0].note      # سبب عدم التصنيف معلن


def test_classified_frameworks_carry_citations():
    from silk_dynamics_agent import DynamicsAgent
    classified = {"drivers": [{"point": "طلب موسمي مرتفع",
                               "evidence": ["عنوان 1 عن سوق التمور والطلب"]}],
                  "restraints": [], "opportunities": [], "threats": [],
                  "porter": [], "pestel": [], "note": "", "source": "x"}
    with mock.patch.dict(os.environ, {"SEARCH_API_KEY": "k"}):
        with mock.patch("silk_websearch_agent.web_search",
                        return_value=_headlines()), \
             mock.patch("silk_ai_judge.classify_dynamics",
                        return_value=classified):
            rep = DynamicsAgent().run({"product": "تمور", "market": "China"})
    v = rep.findings[0].value
    assert v["classified"] is True
    assert v["drivers"][0]["evidence"]          # لا نقطة بلا سند


def test_classify_dynamics_drops_uncited_points():
    import silk_ai_judge as J
    raw = ('{"drivers":[{"point":"بلا سند","evidence":[]},'
           '{"point":"مسنودة","evidence":[1]}],"restraints":[],'
           '"opportunities":[],"threats":[],"porter":[],"pestel":[],'
           '"note":""}')
    with mock.patch.object(J, "available", return_value=True), \
         mock.patch.object(J, "_call", return_value=raw):
        out = J.classify_dynamics("تمور", "China", _headlines())
    pts = [d["point"] for d in out["drivers"]]
    assert pts == ["مسنودة"]                    # غير المسنود سقط بنيوياً


def test_docx_section5_renders_classified_dynamics():
    import pytest
    pytest.importorskip("docx")
    import tempfile
    from conftest import docx_all_text
    from silk_render import build_view
    from silk_reports import render_docx
    dyn = DataPoint({"classified": True,
                     "drivers": [{"point": "نمو الطلب الرمضاني",
                                  "evidence": ["عنوان مصدر"]}],
                     "restraints": [], "opportunities": [], "threats": [],
                     "porter": [{"force": "قوة المشترين",
                                 "point": "مشترون مؤسسيون",
                                 "evidence": ["عنوان"]}],
                     "pestel": [], "note": ""},
                    "Web Search + Claude تصنيف", 0.7, "أطر مصنّفة", _today())
    view = build_view({"product": "تمور", "hs_code": "080410", "year": 2023,
                       "classified": True, "dynamics": dyn,
                       "markets": [{"country": "China", "iso3": "CHN",
                                    "m49": "156", "total_score": 0.5,
                                    "confidence": 0.5, "components": {}}]})
    path = render_docx(view, os.path.join(tempfile.mkdtemp(), "d.docx"))
    txt = docx_all_text(path)
    assert "نمو الطلب الرمضاني" in txt and "الدليل: عنوان مصدر" in txt
    assert "قوى المنافسة الخمس" in txt and "قوة المشترين" in txt
