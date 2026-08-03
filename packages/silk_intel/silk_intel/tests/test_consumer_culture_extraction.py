"""ثقافة المستهلك = رؤًى مستخلَصة لا روابط خام — بلاغ المالك «ترسل روابط = أنت
قوقل». الطبقة ٣ (كلود) تقرأ عناوينَ بحثِ الويب وتُخرج رؤًى مبنيّةً موسومةً بدليلها؛
لا اختلاق، وبلا مفتاحٍ يبقى الغيابُ ظاهرًا (None) لا مُصطنَعًا.
"""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from silk_data_layer import DataPoint, _today  # noqa: E402


def _headlines():
    return [
        DataPoint({"title": "إقبال كبير على العصائر الطبيعية في رمضان بعُمان",
                   "snippet": "يرتفع الطلب على العصائر الطازجة خلال الشهر الفضيل",
                   "link": "https://ex.com/a"}, "Web Search", 0.6, "hit", _today()),
        DataPoint({"title": "المستهلك العُماني يفضّل المنتجات الخالية من السكر",
                   "snippet": "توجه صحي متزايد", "link": "https://ex.com/b"},
                  "Web Search", 0.6, "hit", _today()),
    ]


def test_extraction_returns_grounded_insights_with_evidence():
    import silk_ai_judge as J
    captured = {}

    def fake_call(system, user, max_tokens=700, model=None, timeout=None):
        captured["user"] = user
        captured["model"] = model
        return ('{"insights":[{"point":"موسمية رمضان ترفع الطلب على العصائر",'
                '"evidence":[1]},{"point":"توجّه صحي نحو الخالي من السكر",'
                '"evidence":[2]}],"note":"عيّنة عناوين محدودة"}')

    with mock.patch("silk_ai_judge.available", return_value=True), \
         mock.patch("silk_ai_judge._call", side_effect=fake_call):
        out = J.consumer_culture("عصير", "عُمان", _headlines())

    assert out and out["grounded"] is True
    pts = [i["point"] for i in out["insights"]]
    assert "موسمية رمضان ترفع الطلب على العصائر" in pts
    # الدليل مُعاد كنصِّ العنوان لا كرقم — رؤية مسنودة لمصدرها
    ev = out["insights"][0]["evidence"]
    assert ev and "رمضان" in ev[0]
    # المدخل معزول ضد الحقن، والنموذج السريع مُستخدَم (لا يعلّق التحليل)
    assert "[RAW_FINDINGS_START]" in captured["user"]
    assert captured["model"] == J._FAST_MODEL


def test_extraction_none_without_key_never_fabricates():
    import silk_ai_judge as J
    with mock.patch("silk_ai_judge.available", return_value=False):
        assert J.consumer_culture("عصير", "عُمان", _headlines()) is None


def test_extraction_none_on_empty_headlines():
    import silk_ai_judge as J
    with mock.patch("silk_ai_judge.available", return_value=True):
        assert J.consumer_culture("عصير", "عُمان", []) is None


def test_extraction_none_on_non_json_reply_no_fabrication():
    import silk_ai_judge as J
    with mock.patch("silk_ai_judge.available", return_value=True), \
         mock.patch("silk_ai_judge._call", return_value="عذراً لا أستطيع"):
        assert J.consumer_culture("عصير", "عُمان", _headlines()) is None


def test_view_prefers_extracted_over_raw_links():
    """المخرج الموحّد يعرض الرؤى المستخلَصة؛ الروابط الخام تبقى للاستشهاد فقط."""
    import silk_render as R
    result = {
        "websearch": [DataPoint({"title": "عنوان", "link": "https://x"},
                                "Web Search", 0.6, "hit", _today())],
        "consumer_culture": {"insights": [{"point": "رؤية", "evidence": ["عنوان"]}],
                             "note": "", "grounded": True},
    }
    cc = R._consumer_culture(result)
    assert cc["grounded"] is True
    assert cc["insights"][0]["point"] == "رؤية"
    assert cc["raw"] and cc["raw"][0]["title"] == "عنوان"   # مُتاح للاستشهاد


def test_view_falls_back_to_raw_when_no_extraction():
    import silk_render as R
    result = {"websearch": [DataPoint({"title": "عنوان", "link": None},
                                      "Web Search", 0.6, "hit", _today())]}
    cc = R._consumer_culture(result)
    assert cc["grounded"] is False
    assert cc["insights"] == []
    assert cc["raw"][0]["title"] == "عنوان"


def test_ui_renders_extracted_insights_not_just_links():
    html = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "web", "index.html"), encoding="utf-8").read()
    assert "consumer_culture" in html
    # الواجهة الجديدة (النموذج الملزم): الرؤى تُعرض ببطاقة «ثقافة المستهلك»
    # وكل رؤية بدليلها — لا روابط خام.
    assert "ثقافة المستهلك ونبض السوق" in html and "الدليل:" in html
