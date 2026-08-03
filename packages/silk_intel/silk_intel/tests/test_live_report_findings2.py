"""اختبارات من مراجعة ثانية لتقرير حي (عصائر → اليمن، Railway) — إصلاحان
حقيقيان وُجدا وأُصلحا:

1) محلات عصير/مطاعم كانت تُعرَض كأنها «مستوردون/موزّعون» بلا تمييز — بلاغ
   مالك حرفي: "يستخدم محلات العصير العادية ويقول انهم مستوردين". تصنيف
   Google Places الفعلي (types) كان يُهمَل تماماً؛ الآن يُستخرَج ويُستهلَك
   لإعلان «يبدو محل تجزئة/مطعماً» بدل الادّعاء الضمني بأنه موزّع بالجملة.
2) سنة البيانات كانت تعلق على أرقام ثابتة تتقادم (2022 في المحرك، 2023
   افتراضي الواجهة رغم توفّر 2024 في القائمة نفسها) — بلاغ مالك: "البيانات
   قديمة يمديك الى 2024". الافتراضات الآن محسوبة من تاريخ اليوم.
"""
import datetime
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from silk_data_layer import DataPoint, _today  # noqa: E402


# ── ١) تصنيف نوع العمل من Google Places ──────────────────────────────────────

def test_find_places_extracts_google_types_field():
    import silk_maps_agent as M
    payload = {"status": "OK", "results": [
        {"name": "City Juice Restaurant", "rating": 4.1,
         "formatted_address": "Sanaa", "types": ["restaurant", "food",
                                                  "point_of_interest"]},
        {"name": "Yemen Trading Co", "rating": 4.5,
         "formatted_address": "Sanaa", "types": ["point_of_interest",
                                                  "establishment"]}]}
    resp = mock.MagicMock(status_code=200)
    resp.raise_for_status.return_value = None
    resp.json.return_value = payload
    with mock.patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "k"}), \
         mock.patch("requests.get", return_value=resp):
        found = M.find_places("juice Yemen")
    by_name = {f.value["name"]: f.value["types"] for f in found}
    assert by_name["City Juice Restaurant"] == ["restaurant", "food",
                                                "point_of_interest"]
    assert by_name["Yemen Trading Co"] == ["point_of_interest", "establishment"]


def test_business_hint_flags_restaurant_not_wholesale_distributor():
    import silk_research as R
    assert R._business_hint(["restaurant", "food"]) == "retail_or_food_service"
    assert R._business_hint(["cafe"]) == "retail_or_food_service"
    assert R._business_hint(["point_of_interest", "establishment"]) is None
    assert R._business_hint([]) is None
    assert R._business_hint(None) is None


def test_entities_and_references_excludes_retail_food_service():
    """بلاغ المالك «كل البيانات محلات تجزئة»: محل التجزئة/المطعم يُستبعَد كلياً
    من قائمة المرشّحين (لا يُعرض كموزّع/مستورد)، ويُعاد عدد المُستبعَد ليُعلَن؛
    ويبقى الكيان الحقيقي فقط. Retail is excluded, not merely flagged."""
    import silk_research as R
    juice_shop = DataPoint({"name": "City Juice Restaurant", "rating": 4.1,
                            "address": "Sanaa", "types": ["restaurant"]},
                           "Google Maps", 0.7, "place", _today())
    trading_co = DataPoint({"name": "Yemen Trading Co", "rating": 4.5,
                           "address": "Sanaa", "types": ["establishment"]},
                          "Google Maps", 0.7, "place", _today())
    with mock.patch("silk_maps_agent.find_places",
                    return_value=[juice_shop, trading_co]), \
         mock.patch("silk_websearch_agent.web_search", return_value=[]):
        out, _refs, dropped = R._entities_and_references(["q"], "mq")
    names = [e["name"] for e in out]
    assert "City Juice Restaurant" not in names   # محل تجزئة مُستبعَد
    assert names == ["Yemen Trading Co"]           # الكيان الحقيقي فقط باقٍ
    assert dropped == 1                            # وعددُ المُستبعَد مُعلَن
    assert out[0]["business_hint"] is None


def test_agent_qualifies_entities_with_claude_when_available():
    """بلاغ المالك «ليش أضفنا وكلاء عشان يفلترون النتائج»: عند توفّر مفتاح كلود
    يفلتر **الوكيل** بذكاءٍ (لا قائمة كلمات) — يصنّف المرشّحين ويُبقي الموزّع/
    المستورد الحقيقي فقط، مستنداً للمعطى لا مخترعاً."""
    import silk_research as R
    raw = [{"name": "متجر الحيّ للعصائر", "address": "صنعاء", "types": ["store"]},
           {"name": "شركة اليمن للاستيراد والتوزيع", "address": "عدن", "types": []}]
    calls = {}

    def fake_call(system, user, max_tokens=400, model=None, timeout=None):
        calls["user"] = user
        return '{"keep":[1]}'   # الوكيل أبقى الكيان التجاري الحقيقي فقط
    with mock.patch("silk_ai_judge.available", return_value=True), \
         mock.patch("silk_ai_judge._call", side_effect=fake_call):
        kept, dropped = R._qualify_entities(raw, "عصير", "اليمن", "موزّع أو مستورد بالجملة")
    assert [e["name"] for e in kept] == ["شركة اليمن للاستيراد والتوزيع"]
    assert dropped == 1
    assert "[RAW_FINDINGS_START]" in calls["user"]   # المدخل معزول (ضد الحقن)


def test_report_text_warns_on_retail_hint_never_asserts_wholesale_silently():
    from silk_reports import _entry_text
    shop = {"kind": "entity", "name": "City Juice Restaurant",
           "business_hint": "retail_or_food_service", "via": "Google Maps",
           "retrieved_at": _today()}
    trader = {"kind": "entity", "name": "Yemen Trading Co",
             "business_hint": None, "via": "Google Maps",
             "retrieved_at": _today()}
    shop_line, trader_line = _entry_text(shop), _entry_text(trader)
    assert "⚠" in shop_line and "محل تجزئة" in shop_line
    assert "⚠" not in trader_line


def test_ui_renders_retail_hint_warning():
    html = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "web", "index.html"),
        encoding="utf-8").read()
    assert "business_hint" in html and "retail_or_food_service" in html
    # الواجهة الجديدة: التحذير يُعرض نصاً عربياً ملاصقاً لاسم العمل.
    assert "قد يكون محل تجزئة" in html


# ── ٢) سنة البيانات الافتراضية محسوبة لا ثابتة ───────────────────────────────

def test_engine_default_year_is_latest_with_declared_fallback():
    """P5 (طلب المالك: تغطية أحدث سنة): الافتراضي today-1 — التراجع السنوي
    المعلن (_imports_with_fallback + data_year) يلتقط أحدث سنة منشورة فعلاً
    سوقاً-بسوق، فطلب سنة حديثة لم يعد يفرّغ التقرير (بلاغ أناناس→عُمان)."""
    import silk_engine
    assert silk_engine._default_year() == datetime.date.today().year - 1
    assert silk_engine._default_year() != 2022   # ليس رقماً ثابتاً عالقاً


def test_tariffs_agent_default_year_computed_not_hardcoded():
    import silk_tariffs_agent as T
    expected = datetime.date.today().year - 3
    assert T._default_year() == expected
    assert T._default_year() != 2021


def test_ui_year_dropdown_defaults_computed_from_today():
    html = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "web", "index.html"),
        encoding="utf-8").read()
    assert "new Date().getFullYear()" in html
    # P5: الافتراضي today-1 (أحدث سنة) — التراجع المعلن خادمياً يغطي ما لم
    # يُنشر بعد؛ الواجهة: to = CURY-1 داخل years() — نفس العقد.
    assert "CURY-1" in html
    # لا قائمة سنوات ثابتة عالقة بعد الآن.
    assert "[2024,2023,2022,2021,2020,2019,2018,2017]" not in html
