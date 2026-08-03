"""استخلاص الأسماء والأسعار من الويب — بلاغ المالك المتكرّر «ترسل روابط = أنت
قوقل». الطبقة ٣ (كلود) تقرأ عناوينَ البحث فتستخرج أسماءَ الشركاتِ (لا الأدلّة/
المجمّعات) والأسعارَ المذكورةَ صراحةً — مع دليلها، بلا اختلاق. بلا مفتاح: تبقى
الروابطُ خامًا (تراجُع صادق) لا يُدَّعى استخلاص.
"""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from silk_data_layer import DataPoint, _today  # noqa: E402


def _refs():
    return [
        DataPoint({"title": "Maryland Global | Import & Export, FMCG Distribution",
                   "snippet": "موزّع أغذية في عمّان", "link": "https://m.jo"},
                  "Web Search", 0.3, "hit", _today()),
        DataPoint({"title": "Top Wholesale companies in Jordan - Lusha",
                   "snippet": "directory", "link": "https://lusha.com"},
                  "Web Search", 0.3, "hit", _today()),
    ]


# ── استخلاص الشركات ─────────────────────────────────────────────────────────

def test_extract_companies_pulls_names_drops_directories():
    import silk_ai_judge as J
    captured = {}

    def fake_call(system, user, max_tokens=600, model=None, timeout=None):
        captured["user"] = user
        captured["model"] = model
        # الوكيل أبقى الشركة الحقيقية واستبعد دليلَ Lusha
        return '{"companies":[{"name":"Maryland Global","evidence":1}],"note":""}'

    with mock.patch("silk_ai_judge.available", return_value=True), \
         mock.patch("silk_ai_judge._call", side_effect=fake_call):
        out = J.extract_companies(_refs(), "ليمون", "الأردن", "موزّع أو مستورد")

    assert [c["name"] for c in out] == ["Maryland Global"]
    assert out[0]["url"] == "https://m.jo"          # الدليل مربوطٌ بمصدره
    assert "مُستخلَص" in out[0]["note"]
    assert "[RAW_FINDINGS_START]" in captured["user"]  # معزول ضد الحقن
    assert captured["model"] == J._FAST_MODEL


def test_extract_companies_none_without_key():
    import silk_ai_judge as J
    with mock.patch("silk_ai_judge.available", return_value=False):
        assert J.extract_companies(_refs(), "ليمون", "الأردن", "موزّع") is None


def test_extract_companies_none_on_empty_or_bad_json():
    import silk_ai_judge as J
    with mock.patch("silk_ai_judge.available", return_value=True), \
         mock.patch("silk_ai_judge._call", return_value="لا أستطيع"):
        assert J.extract_companies(_refs(), "ليمون", "الأردن", "موزّع") is None


# ── استخلاص الأسعار ─────────────────────────────────────────────────────────

def test_extract_prices_only_explicit_numbers():
    import silk_ai_judge as J
    refs = [DataPoint({"title": "كيلو الليمون يقترب من الـ4 دنانير في الأردن",
                       "snippet": "", "link": "https://ig.com/x"},
                      "Web Search", 0.3, "hit", _today())]

    def fake_call(system, user, max_tokens=500, model=None, timeout=None):
        return '{"prices":[{"price":4,"currency":"JOD","unit":"kg","evidence":1}],"note":""}'

    with mock.patch("silk_ai_judge.available", return_value=True), \
         mock.patch("silk_ai_judge._call", side_effect=fake_call):
        out = J.extract_prices(refs, "ليمون", "الأردن")

    assert out[0]["price"] == 4 and out[0]["currency"] == "JOD"
    assert out[0]["unit"] == "kg" and out[0]["url"] == "https://ig.com/x"


def test_extract_prices_drops_entries_without_a_number():
    import silk_ai_judge as J
    refs = [DataPoint({"title": "Lemon price guide", "link": "https://x"},
                      "Web Search", 0.3, "hit", _today())]
    with mock.patch("silk_ai_judge.available", return_value=True), \
         mock.patch("silk_ai_judge._call",
                    return_value='{"prices":[{"price":null,"evidence":1}],"note":"لا رقم"}'):
        assert J.extract_prices(refs, "ليمون", "الأردن") is None


# ── التكامل في الوكلاء: لا تكرار، واستخلاص بدل السرد ─────────────────────────

def test_entities_references_no_duplicate_web_dump_keyless():
    """إصلاح: كانت حلقةُ عناوين الويب تتكرّر فيتضاعف السرد. بلا مفتاح: مرجعٌ واحد
    لكلِّ رابطٍ فريد (لا تكرار)."""
    import silk_research as R
    hit = DataPoint({"title": "Acme Trading", "link": "https://acme.jo"},
                    "Web Search", 0.3, "hit", _today())
    with mock.patch("silk_maps_agent.find_places", return_value=[]), \
         mock.patch("silk_websearch_agent.web_search", return_value=[hit]), \
         mock.patch("silk_ai_judge.available", return_value=False):
        out, _refs, _drop = R._entities_and_references(["q1"], "mq",
                                                       product="ليمون",
                                                       market="الأردن")
    refs = [e for e in out if e.get("kind") == "reference"]
    assert len(refs) == 1              # لا تضاعُف بعد الآن


def test_entities_references_extracts_companies_when_claude_available():
    """مع مفتاح كلود: تُستخلَص أسماءُ الشركاتِ (kind=entity) بدل سردِ الروابط."""
    import silk_research as R
    hit = DataPoint({"title": "Maryland Global Import & Export",
                     "link": "https://m.jo"}, "Web Search", 0.3, "hit", _today())
    with mock.patch("silk_maps_agent.find_places", return_value=[]), \
         mock.patch("silk_websearch_agent.web_search", return_value=[hit]), \
         mock.patch("silk_ai_judge.available", return_value=True), \
         mock.patch("silk_ai_judge.extract_companies",
                    return_value=[{"name": "Maryland Global",
                                   "url": "https://m.jo", "note": "مُستخلَص من الويب"}]):
        out, _refs, _drop = R._entities_and_references(["q1"], "mq",
                                                       product="ليمون",
                                                       market="الأردن")
    names = [e["name"] for e in out if e.get("kind") == "entity"]
    assert "Maryland Global" in names
    ent = next(e for e in out if e.get("name") == "Maryland Global")
    assert ent["via"] == "Web → Claude"
