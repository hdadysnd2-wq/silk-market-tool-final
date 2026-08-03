"""تعريفة منظمة التجارة العالمية لسِلك — Silk WTO Tariff & Trade Data (TTD) agent.

يجلب التعريفة المطبَّقة (MFN/تفضيلية) لرمز HS إلى السوق المستهدف من واجهة WTO
Timeseries (خلف بوابة ttd.wto.org). الهدف: سدّ فجوة التعريفة الثنائية المزمنة
في WITS للأسواق الأوروبية (بلاغ هولندا/HS 080410) — WTO TTD يحمل تعريفة الاتحاد
الموحّدة صراحةً حين لا يعيدها WITS.

عقود المنصّة (الموجة: دمج مصادر جديدة) — نفس عقود silk_imf_agent حرفياً:
  • **مفتاح مطلوب:** واجهة WTO Timeseries تتطلب اشتراكاً مجانياً
    (`Ocp-Apim-Subscription-Key`). المفتاح غائب => فجوة معلنة فوراً بلا أي
    نداء شبكة (لا محاولة بلا مفتاح، لا اختلاق مفتاح).
  • **لا اختلاق:** أي فشل => DataPoint(None، ثقة 0.0) + ملاحظة السبب.
  • **إعلان للمشغّل:** فشل الجلب => `record_service_failure` (عائلة C، الدرس ٢٦).
  • **مخزَّن مؤقتاً:** الجلب عبر `silk_cache.cached_get`.
  • **بلا كشط:** واجهة JSON رسمية معلَنة فقط.

Env:
  WTO_TTD_API_KEY | WTO_API_KEY — مفتاح اشتراك WTO Timeseries (مجاني بالتسجيل).

Public docs: https://apiportal.wto.org/  ·  https://ttd.wto.org/
Response shape (recorded from the public API docs, لقطة مرجعية مثبتة في
`tests/test_wave_datasources_integration.py`):
  {"Dataset": [{"Value": 8.0, "Year": 2021, "ProductOrSectorCode": "080410",
                "ReportingEconomyCode": "918", "Unit": "Percent"}]}
"""
from __future__ import annotations

import datetime
import logging
import os

from silk_data_layer import DataPoint, ISO3_TO_M49, _today
# نعيد استخدام منطق ترميز المُبلِّغ من وكيل WITS (عضو الاتحاد الأوروبي => 918)
# — نفس تعريفة الاتحاد الموحّدة، فلا نكرّر جدول الدول.
from silk_tariffs_agent import _hs6, _wits_reporter_code

log = logging.getLogger(__name__)

_WTO_BASE = "https://api.wto.org/timeseries/v1/data"
_TTL = 30 * 86400  # التعريفات تتغيّر بطيئاً — تخزين شهر رخيص.
# رمز مؤشر التعريفة المطبَّقة (AVE, MFN applied simple average) في WTO Timeseries.
_INDICATOR_MFN_APPLIED = "TP_A_0010"


def wto_api_key() -> str:
    """مفتاح WTO Timeseries — WTO_TTD_API_KEY أو الاسم البديل WTO_API_KEY."""
    return (os.environ.get("WTO_TTD_API_KEY", "").strip()
            or os.environ.get("WTO_API_KEY", "").strip())


def _default_year() -> int:
    """آخر سنة على الأرجح متاحة — التعريفة أبطأ من التجارة العادية سنتين+."""
    return datetime.date.today().year - 3


def _parse_value(payload: object) -> tuple[float | None, int | None]:
    """استخرج أول قيمة تعريفة رقمية + سنتها من ردّ WTO Timeseries.

    الشكل الرسمي: {"Dataset": [{"Value": .., "Year": ..}, ...]}. دفاعي — يقبل
    اختلاف حالة المفاتيح ويتجاهل ما لا يُفسَّر رقماً؛ لا شيء => (None, None)."""
    if not isinstance(payload, dict):
        return None, None
    rows = payload.get("Dataset") or payload.get("dataset") or payload.get("data")
    if not isinstance(rows, list):
        return None, None
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw = row.get("Value", row.get("value"))
        try:
            val = float(raw)
        except (TypeError, ValueError):
            continue
        yr_raw = row.get("Year", row.get("year"))
        try:
            yr = int(yr_raw)
        except (TypeError, ValueError):
            yr = None
        return val, yr
    return None, None


def wto_applied_tariff(hs_code: str, market_iso3: str,
                       partner_iso3: str = "SAU",
                       year: int | None = None) -> DataPoint:
    """التعريفة المطبَّقة (%) من WTO TTD — best-effort، فجوة معلنة عند أي فشل.

    مفتاح غائب => فجوة معلنة فوراً بلا نداء (لا اختلاق). النجاح => DataPoint
    بمصدر «WTO TTD» ونسبة مئوية وسنة موسومة.
    """
    hs6 = _hs6(hs_code)
    if not hs6:
        return DataPoint(None, "WTO TTD", 0.0,
                         f"رمز HS غير صالح {hs_code!r}", _today())
    key = wto_api_key()
    if not key:
        # غياب المفتاح ليس عطلاً — تدهور نظيف معلن بلا نداء شبكة ولا إعلان
        # عطل للمشغّل (لا شيء فشل، الخدمة ببساطة غير مُهيَّأة).
        return DataPoint(None, "WTO TTD", 0.0,
                         "WTO TTD غير مُهيَّأ (WTO_TTD_API_KEY غير مضبوط) — "
                         "فجوة معلنة، لا محاولة جلب بلا مفتاح", _today())
    reporter_code, is_eu = _wits_reporter_code(market_iso3)
    partner_m49 = ISO3_TO_M49.get((partner_iso3 or "").upper())
    if not reporter_code:
        return DataPoint(None, "WTO TTD", 0.0,
                         f"لا رمز رقمي معروف لـ{market_iso3!r} في فهرس WTO — "
                         "فجوة معلنة (لا استعلام بلا رمز)", _today())
    year = year or _default_year()
    params = {
        "i": _INDICATOR_MFN_APPLIED,
        "r": reporter_code,
        "pc": hs6,
        "ps": str(year),
        "fmt": "json",
        "mode": "full",
    }
    if partner_m49:  # الشريك اختياري — MFN المطبَّق لا يعتمد على الشريك عادةً
        params["p"] = partner_m49.zfill(3)
    # المفتاح في **ترويسة** لا في الاستعلام (الآلية الموثّقة لبوابة WTO/Azure
    # APIM) — فلا يظهر السرّ في الـURL (تدقيق مراجعة: منع تسرّب المفتاح لسجلّات
    # الوسطاء/البروكسي). لا يدخل مفتاح التخزين المؤقت (ثابت للخادم).
    headers = {"Ocp-Apim-Subscription-Key": key}
    try:
        from silk_data_layer import _http_get
        from silk_cache import cached_get
        data = cached_get(_WTO_BASE, params=params, ttl_seconds=_TTL,
                          fetcher=_http_get, headers=headers)
    except Exception as e:  # noqa: BLE001 — لا استثناء يصل المستدعي
        data = None
        _record_failure(hs6, market_iso3, f"{type(e).__name__}: {e}")
    if data is None:
        note = (f"WTO TTD غير متاح الآن لـHS{hs6} {market_iso3} {year} — "
                "تعذّر الجلب، فجوة معلنة")
        log.warning(note)
        _record_failure(hs6, market_iso3, "cached_get returned None")
        return DataPoint(None, "WTO TTD", 0.0, note, _today(),
                         status="fetch_failed")
    rate, got_year = _parse_value(data)
    if rate is None:
        note = (f"WTO TTD لا تعريفة قابلة للتفسير لـHS{hs6} {market_iso3} "
                f"{year} — فجوة معلنة")
        log.info(note)
        return DataPoint(None, "WTO TTD", 0.0, note, _today(),
                         status="no_record")
    eu_note = (" — تعريفة الاتحاد الأوروبي الموحّدة (WTO المُبلِّغ: EU/918)"
               if is_eu else "")
    return DataPoint(
        round(rate, 2), "WTO TTD", 0.9,
        f"التعريفة المطبَّقة % HS{hs6} إلى {market_iso3} "
        f"{got_year or year} (MFN applied، WTO Tariff & Trade Data){eu_note}",
        _today())


def _record_failure(hs6: str, iso3: str, detail: str) -> None:
    """إعلان فشل الجلب للمشغّل — عائلة C (الدرس ٢٦)، قناة جانبية صامتة."""
    try:
        import silk_ops_log
        silk_ops_log.record_service_failure(
            "wto_ttd", f"WTO TTD HS{hs6}/{iso3}: {detail}",
            context={"source": "wto_ttd", "hs6": hs6, "iso3": iso3})
    except Exception:  # noqa: BLE001
        pass


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Silk WTO TTD agent — best-effort (declared gap without WTO_TTD_API_KEY)")
    dp = wto_applied_tariff("080410", "NLD", "SAU", 2021)
    print(f"  NLD HS080410: {dp.value} — {dp.note}")
