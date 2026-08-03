"""اختبارات من مراجعة أول تقرير حي (دقيق قمح → الإمارات، Railway) — إصلاح
حقيقي واحد وُجد وأُصلح: ملحق أثر المصادر لا يرى حزمة البحث (Stage 3).

`_walk_dps`/`_provenance` كانا يطابقان `"source" in obj and "value" in obj`
(نمط DataPoint المسطّح القديم) فقط — بينما اكتشافات §4b تحمل `sources[]`
جمعاً (مصادر متعددة محتملة، تثليث Serper/Maps/مرآة السعودية)، فتغيب تماماً
عن الملحق الإجمالي رغم مساهمتها الفعلية — التقرير الحي أظهر «Serper 21/21»
بينما استهلكت وكلاء §4b نداءات Serper/Maps إضافية غير محسوبة إطلاقاً.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from silk_render import _provenance, _walk_dps  # noqa: E402


def test_research_bundle_findings_are_counted_in_provenance_appendix():
    """اكتشاف §4b بمصدرين (تثليث) يظهر في الملحق لكل مصدر على حدة."""
    result = {"markets": [{"research": {"agents": {"competitor": {
        "findings": [
            {"metric": "saudi_share_pct", "value": 30.0, "unit": "%",
             "modeled": False, "formula": None, "note": "مثلَّث",
             "sources": [{"source": "UN Comtrade", "confidence": 0.9,
                         "retrieved_at": "2026-07-06", "url": None},
                        {"source": "UN Comtrade (تقرير سعودي مباشر — مرآة)",
                         "confidence": 0.9, "retrieved_at": "2026-07-06",
                         "url": None}]},
            {"metric": "named_companies", "value": [{"name": "x"}],
             "modeled": False, "formula": None, "note": "",
             "sources": [{"source": "Google Maps", "confidence": 0.4,
                         "retrieved_at": "2026-07-06", "url": None}]},
        ]}}}}]}
    prov = _provenance(result)
    by_source = {b["source"]: b for b in prov}
    assert by_source["UN Comtrade"]["contributed"] == 1
    assert by_source["UN Comtrade (تقرير سعودي مباشر — مرآة)"]["contributed"] == 1
    assert by_source["Google Maps"]["contributed"] == 1


def test_source_ref_entries_alone_are_not_double_counted():
    """المصدر الفردي (SourceRef) وحده — بلا metric/value محيطين — لا يُطابَق؛
    لا ازدواج عدّ عند تكرار المرور على sources[] أثناء التكرار العام."""
    dps: list = []
    _walk_dps({"source": "Google Maps", "confidence": 0.4,
              "retrieved_at": "2026-07-06", "url": None}, dps)
    assert dps == []   # بلا "value" — ليس DataPoint ولا Finding، فلا يُحسب


def test_legacy_datapoint_shape_still_counted_unchanged():
    """التنسيق القديم (source/value مباشرين) يبقى يعمل كما كان — لا انحدار."""
    result = {"markets": [{"tariff": {"source": "World Bank WITS",
                                      "value": None,
                                      "note": "WITS unavailable: ..."}}]}
    prov = _provenance(result)
    b = next(x for x in prov if x["source"] == "World Bank WITS")
    assert b["attempted"] == 1 and b["contributed"] == 0
    assert b["failures"] == ["WITS unavailable: ..."]
