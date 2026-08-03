"""وكيل يوروستات لسِلك — Silk Eurostat consumption/migration agent
(المرحلة ٢ج، خيار B من مقترح تكامل مصادر جديدة).

إشارتان إضافيتان **لأسواق الاتحاد الأوروبي/EFTA حصراً** — يوروستات لا
يغطي أي سوق آخر، فكل استعلام خارج هذه القائمة يعيد امتناعاً معلناً بلا
أي محاولة جلب (لا فجوة بيانات، بل نطاق مصدر):

1. حصة الغذاء والمشروبات غير الكحولية من إجمالي إنفاق الأسرة (مسح
   ميزانية الأسرة، جدول hbs_str_t223) — إشارة قوة إنفاق فعلية على هذه
   الفئة، لا مجرد الدخل للفرد.
2. عدد السكان المولودين خارج السوق (إحصاءات الهجرة، جدول migr_pop3ctb)
   — إشارة تكميلية أدقّ لحجم الجاليات المهاجرة من الجدول الثابت الحالي
   (demographics_l1.csv)، رقم مطلق لا نسبة (حساب النسبة يتطلب دمجه مع
   ناتج demographics_economy — بعثة أخرى معزولة، خارج نطاق هذه الوظيفة).

**تنبيه تحقّق حي**: رمزا الجدولين أعلاه معروفان طويلا الأمد من كتالوج
يوروستات العام، لكن هذه البيئة بلا اتصال شبكة للتحقق المباشر وقت الكتابة
— يُوصى بفحص حي (٢-٣ نداءات حقيقية، $0) قبل أول استخدام إنتاجي. فشل رمز
جدول خاطئ يتدهور بنفس مسار أي فشل مصدر آخر (None موسوم، لا اختلاق، لا
عطل) — المبدأ التأسيسي يبقى نافذاً حتى لو كان الرمز غير دقيق.

Real data only: any failure (market not EU/EFTA, network, HTTP status,
unexpected JSON-stat shape, missing value) degrades to a provenance-
tagged DataPoint(value=None, confidence=0.0) — never fabricates.
"""
from __future__ import annotations

import logging

import requests

import silk_blocs
from silk_data_layer import DataPoint, _today

log = logging.getLogger(__name__)

_EUROSTAT_BASE = ("https://ec.europa.eu/eurostat/api/dissemination/"
                  "statistics/1.0/data")
_TIMEOUT = 30

# أسواق يوروستات المؤهَّلة — EU27 + EFTA من المصدر الواحد (`silk_blocs`، DEF-2).
# خارج هذه القائمة: يوروستات لا يغطي السوق إطلاقاً.
EU_EFTA_MARKETS = silk_blocs.EU_EFTA

# استثناء رمز يوروستات الجغرافي عن ISO2 القياسي — اليونان EL لا GR (الاستثناء
# التاريخي الوحيد المهم عملياً لأسواق سِلك المتوقّعة).
_GEO_OVERRIDE = {"GRC": "EL"}

# جدول هيكل إنفاق الأسر (مسح ميزانية الأسرة، دورة كل ~٥ سنوات) — نسبة
# الغذاء والمشروبات غير الكحولية (COICOP CP01) من إجمالي الإنفاق الاستهلاكي.
_HBS_DATASET = "hbs_str_t223"
_HBS_COICOP_FOOD = "CP01"

# جدول السكان حسب بلد الميلاد (إحصاءات الهجرة) — c_birth=FOR: مولودون خارج
# السوق المُبلِّغة.
_MIGR_DATASET = "migr_pop3ctb"


def _eligible(iso3: str) -> bool:
    return (iso3 or "").strip().upper() in EU_EFTA_MARKETS


def _geo_code(iso3: str, iso2: str | None) -> str | None:
    override = _GEO_OVERRIDE.get((iso3 or "").strip().upper())
    if override:
        return override
    return (iso2 or "").strip().upper() or None


def _not_eligible_dp(source: str, iso3: str, signal_label: str) -> DataPoint:
    return DataPoint(
        None, source, 0.0,
        f"يوروستات لا يغطي {iso3} — مقتصر على أسواق الاتحاد الأوروبي/"
        f"EFTA؛ {signal_label} غير قابل للتطبيق هنا (نطاق مصدر لا فجوة "
        "بيانات)", _today())


def _fetch_jsonstat(dataset: str, params: dict) -> dict | None:
    """نداء يوروستات خام — Eurostat JSON-stat 2.0 dissemination API.

    None على أي فشل (شبكة/حالة HTTP/تنسيق غير متوقّع) — لا اختلاق. كل
    استعلام هنا بجغرافيا واحدة + فئة واحدة + إما سنة محدَّدة أو
    lastTimePeriod=1 (أحدث فترة فقط) فتبقى استجابة القيمة الواحدة صالحة
    دون الحاجة لحساب فهرس JSON-stat متعدد الأبعاد الكامل.
    """
    url = f"{_EUROSTAT_BASE}/{dataset}"
    q = {"format": "JSON", "lang": "EN", **params}
    try:
        r = requests.get(url, params=q, timeout=_TIMEOUT)
        r.raise_for_status()
        payload = r.json()
    except Exception as e:  # noqa: BLE001 — شبكة/HTTP/تنسيق، لا يُرفَع للمستدعي
        log.warning("Eurostat fetch failed (%s, %s): %s", dataset, q, e)
        try:  # عائلة C (Wave 1.5): إعلان الفشل للمشغّل.
            import silk_ops_log
            silk_ops_log.record_service_failure(
                "eurostat", f"Eurostat fetch failed ({dataset}): {e}")
        except Exception:  # noqa: BLE001
            pass
        return None
    if not isinstance(payload, dict) or "value" not in payload:
        log.warning("Eurostat unexpected payload shape (%s, %s)", dataset, q)
        return None
    return payload


def _first_value(payload: dict) -> float | None:
    """أول قيمة رقمية فعلية من استجابة JSON-stat 2.0 — 'value' قد تكون
    قاموساً متفرقاً (مفتاح=فهرس نصي) أو مصفوفة كثيفة، كلا الشكلين معياريان
    في JSON-stat 2.0؛ استعلامنا بجغرافيا+فئة+فترة زمنية واحدة يجعل بند
    واحد الحالة العملية الشائعة."""
    raw = payload.get("value")
    if isinstance(raw, dict):
        raw = next(iter(raw.values()), None)
    elif isinstance(raw, list):
        raw = raw[0] if raw else None
    if raw is None or isinstance(raw, bool):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _time_params(year: int | None) -> dict:
    return {"time": str(year)} if year is not None else {"lastTimePeriod": 1}


def household_food_expenditure_share(iso3: str, iso2: str | None,
                                     year: int | None = None) -> DataPoint:
    """حصة الغذاء والمشروبات من إنفاق الأسرة — % من إجمالي الإنفاق
    الاستهلاكي (مسح ميزانية الأسرة، يوروستات). EU/EFTA فقط."""
    if not _eligible(iso3):
        return _not_eligible_dp("Eurostat HBS", iso3, "حصة إنفاق الغذاء")
    geo = _geo_code(iso3, iso2)
    if not geo:
        return DataPoint(None, "Eurostat HBS", 0.0,
                         f"لا رمز جغرافي ليوروستات لـ{iso3}", _today())
    params = {"geo": geo, "coicop": _HBS_COICOP_FOOD, "unit": "PC",
             **_time_params(year)}
    payload = _fetch_jsonstat(_HBS_DATASET, params)
    if payload is None:
        return DataPoint(None, "Eurostat HBS", 0.0,
                         f"تعذّر جلب حصة إنفاق الغذاء لـ{iso3}", _today())
    value = _first_value(payload)
    if value is None:
        return DataPoint(None, "Eurostat HBS", 0.0,
                         f"لا سجل لحصة إنفاق الغذاء لـ{iso3} "
                         f"{year or '(أحدث فترة)'}", _today())
    return DataPoint(
        value, "Eurostat (مسح ميزانية الأسرة)", 0.75,
        f"حصة الغذاء والمشروبات غير الكحولية من إجمالي إنفاق الأسرة "
        f"{iso3} {year or '(أحدث سنة منشورة)'} % — مسح دوري (~٥ سنوات)، "
        "لا سنوي", _today())


def foreign_born_population_count(iso3: str, iso2: str | None,
                                  year: int | None = None) -> DataPoint:
    """عدد السكان المولودين خارج السوق — يوروستات (إحصاءات الهجرة). رقم
    مطلق لا نسبة — اقسمه على السكان الكلي (worldbank_indicator
    indicator='population' من بعثة أخرى) لحساب النسبة؛ خارج نطاق هذه
    الوظيفة المعزولة. مؤشّر تكميلي لحجم الجاليات المهاجرة، لا بديلاً عن
    نسبة المسلمين الثابتة (لا صلة دينية مباشرة في بيانات يوروستات).
    EU/EFTA فقط."""
    if not _eligible(iso3):
        return _not_eligible_dp("Eurostat migration", iso3,
                                "عدد السكان المولودين خارج السوق")
    geo = _geo_code(iso3, iso2)
    if not geo:
        return DataPoint(None, "Eurostat migration", 0.0,
                         f"لا رمز جغرافي ليوروستات لـ{iso3}", _today())
    params = {"geo": geo, "c_birth": "FOR", **_time_params(year)}
    payload = _fetch_jsonstat(_MIGR_DATASET, params)
    if payload is None:
        return DataPoint(None, "Eurostat migration", 0.0,
                         f"تعذّر جلب عدد السكان المولودين خارج {iso3}",
                         _today())
    value = _first_value(payload)
    if value is None:
        return DataPoint(None, "Eurostat migration", 0.0,
                         f"لا سجل لعدد السكان المولودين خارج {iso3} "
                         f"{year or '(أحدث فترة)'}", _today())
    return DataPoint(
        value, "Eurostat (إحصاءات الهجرة)", 0.75,
        f"عدد السكان المولودين خارج {iso3} {year or '(أحدث سنة منشورة)'} "
        "(رقم مطلق) — مؤشّر تكميلي لحجم الجاليات المهاجرة، اقسمه على "
        "السكان الكلي لحساب النسبة، لا بديلاً عن نسبة المسلمين", _today())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Silk Eurostat agent — EU/EFTA only, degrades gracefully offline "
         "or outside coverage")
    for iso3, iso2 in (("NLD", "NL"), ("SAU", "SA")):
        dp1 = household_food_expenditure_share(iso3, iso2)
        dp2 = foreign_born_population_count(iso3, iso2)
        print(f"  {iso3} HBS food share: value={dp1.value} note={dp1.note}")
        print(f"  {iso3} foreign-born count: value={dp2.value} "
             f"note={dp2.note}")
