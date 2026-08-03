"""وكيل صندوق النقد الدولي لسِلك — Silk IMF macro-risk data agent.

يجلب مؤشرات الاقتصاد الكلي من واجهة IMF DataMapper العامة (WEO) — نمو الناتج
المحلي الحقيقي، التضخم، ورصيد الحساب الجاري — لإثراء قسم المخاطر/الاقتصاد الكلي
بجانب بيانات صرف البنك الدولي القائمة. الواجهة مجانية بلا مفتاح.

يتبع نفس عقود المنصّة حرفياً (الموجة: دمج مصادر جديدة):
  • **لا اختلاق:** أي فشل (شبكة/شكل/سلسلة غائبة) => DataPoint(None, ثقة 0.0)
    بملاحظة تشرح السبب — لا رقم مُخمَّن أبداً (المبدأ المؤسِّس).
  • **إعلان للمشغّل:** فشل الجلب يُسجَّل عبر `record_service_failure` (عائلة C،
    الدرس ٢٦) فيظهر في `GET /ops/last-errors` — لا فشل صامت.
  • **مخزَّن مؤقتاً:** كل جلب يمرّ عبر `silk_cache.cached_get` (نفس نمط الطبقة ١).
  • **مصدر + سنة موسومان:** كل قيمة تحمل «IMF WEO» والسنة صراحةً.
  • **بلا كشط مخالف للشروط:** واجهة JSON رسمية معلَنة، لا كشط صفحات.

Public docs: https://www.imf.org/external/datamapper/api/help
Response shape (recorded from the public DataMapper API, لقطة مرجعية مثبتة في
`tests/test_wave_datasources_integration.py`):
  {"values": {"NGDP_RPCH": {"NLD": {"2022": 4.35, "2023": 0.06, ...}}}}
"""
from __future__ import annotations

import datetime
import logging
import os

from silk_data_layer import DataPoint, _today

log = logging.getLogger(__name__)

# قاعدة DataMapper — الرمز والبلد يُلحقان لكل نداء.
_IMF_BASE = "https://www.imf.org/external/datamapper/api/v1"
_TTL = 7 * 86400  # بيانات WEO سنوية — تخزين أسبوع كافٍ ورخيص.

# مؤشرات منتقاة (اسم وصفي => رمز WEO + وسم عربي) — لا رموز حرّة يخمّنها كلود،
# نفس انضباط `_WB_INDICATORS` في silk_llm_runtime. أضِف مؤشراً هنا فقط برمز
# WEO رسمي حقيقي.
_IMF_INDICATORS: dict[str, tuple[str, str]] = {
    "gdp_growth": ("NGDP_RPCH",
                   "نمو الناتج المحلي الإجمالي الحقيقي (% سنوي، IMF WEO)"),
    "inflation": ("PCPIPCH",
                  "التضخم — متوسط أسعار المستهلك (% سنوي، IMF WEO)"),
    "current_account": ("BCA_NGDPD",
                        "رصيد الحساب الجاري (% من الناتج، IMF WEO)"),
}


def available_indicators() -> list[str]:
    """أسماء المؤشرات المتاحة — للأداة/الاختبارات."""
    return sorted(_IMF_INDICATORS)


def _pick_year(series: dict, year: int | None) -> tuple[int | None, object]:
    """اختر السنة المطلوبة، وإلا أحدث سنة غير مستقبلية بقيمة رقمية.

    WEO يحوي سنوات تنبؤ مستقبلية — لا نقدّمها كـ«فعلية» بلا تمييز؛ نفضّل أحدث
    سنة ≤ السنة الحالية (تقدير/فعلي)، فإن كانت كل السلسلة مستقبلية أخذنا أحدثها
    صراحةً موسومة بسنتها (لا اختلاق — السنة معلَنة دوماً)."""
    numeric: dict[int, float] = {}
    for y, v in (series or {}).items():
        try:
            numeric[int(y)] = float(v)
        except (TypeError, ValueError):
            continue
    if not numeric:
        return None, None
    if year is not None and year in numeric:
        return year, numeric[year]
    this_year = datetime.date.today().year
    past = [y for y in numeric if y <= this_year]
    chosen = max(past) if past else max(numeric)
    return chosen, numeric[chosen]


def imf_indicator(iso3: str, metric: str, year: int | None = None) -> DataPoint:
    """مؤشر IMF WEO واحد للبلد — best-effort، فجوة معلنة عند أي فشل (لا اختلاق).

    metric: أحد `available_indicators()`. القيمة نسبة مئوية (نمو/تضخم/حساب
    جارٍ). فشل الجلب => None + ثقة 0.0 + إعلان للمشغّل عبر ops log.
    """
    iso = (iso3 or "").strip().upper()
    key = (metric or "").strip().lower()
    entry = _IMF_INDICATORS.get(key)
    if not entry:
        return DataPoint(None, "IMF WEO", 0.0,
                         f"مؤشر IMF غير معروف: {metric!r} — يجب أن يكون أحد "
                         f"{available_indicators()}", _today())
    if not iso or len(iso) != 3:
        return DataPoint(None, "IMF WEO", 0.0,
                         f"رمز دولة ISO3 غير صالح: {iso3!r} — فجوة معلنة",
                         _today())
    code, label = entry
    url = f"{_IMF_BASE}/{code}/{iso}"
    try:
        from silk_data_layer import _http_get
        from silk_cache import cached_get
        data = cached_get(url, params=None, ttl_seconds=_TTL, fetcher=_http_get)
    except Exception as e:  # noqa: BLE001 — لا استثناء يصل المستدعي أبداً
        data = None
        _record_failure(iso, code, f"{type(e).__name__}: {e}")
    if data is None:
        note = (f"IMF WEO غير متاح الآن لـ{iso}/{code} — تعذّر الجلب (شبكة/شكل)، "
                "فجوة معلنة (أعد المحاولة لاحقاً)")
        log.warning(note)
        _record_failure(iso, code, "cached_get returned None")
        return DataPoint(None, "IMF WEO", 0.0, note, _today(),
                         status="fetch_failed")
    # الشكل: {"values": {CODE: {ISO3: {"YYYY": value, ...}}}}
    series = {}
    try:
        series = ((data.get("values") or {}).get(code) or {}).get(iso) or {}
    except AttributeError:
        series = {}
    yr, val = _pick_year(series, year)
    if val is None:
        note = (f"IMF WEO لا سجل لـ{iso}/{code}"
                + (f" سنة {year}" if year else "") + " — فجوة معلنة (لا مرآة)")
        log.info(note)  # ردّ ناجح بلا سجل — ليس عطلاً تقنياً
        return DataPoint(None, "IMF WEO", 0.0, note, _today(),
                         status="no_record")
    # تدقيق مراجعة (#3/#4 — صدق المصدر): قيمة السنة الحالية/المستقبلية في WEO
    # **تقدير/تنبؤ** لا رقم فعليّ — تُوسَم صراحةً وتُخفَّض ثقتها (0.6 لا 0.85)
    # كي لا تُقدَّم بيقين الأرقام المُحقَّقة. والسنة المطلوبة غير المتاحة (استُبدلت
    # بأحدث متاح) تُعلَن صراحةً لا تُمرَّر صامتة كأنها السنة المطلوبة.
    is_estimate = yr >= datetime.date.today().year
    est_tag = " — تقدير/تنبؤ IMF WEO لا قيمة فعلية" if is_estimate else ""
    req_tag = (f" (السنة المطلوبة {year} غير متاحة — أحدث متاح {yr})"
               if year is not None and yr != year else "")
    conf = 0.6 if is_estimate else 0.85
    return DataPoint(round(float(val), 3), "IMF WEO", conf,
                     f"{label} — {iso} سنة {yr} (IMF DataMapper)"
                     f"{est_tag}{req_tag}", _today())


def _record_failure(iso: str, code: str, detail: str) -> None:
    """إعلان فشل الجلب للمشغّل — عائلة C (الدرس ٢٦)، قناة جانبية صامتة."""
    try:
        import silk_ops_log
        silk_ops_log.record_service_failure(
            "imf", f"IMF WEO {code}/{iso}: {detail}",
            context={"source": "imf", "indicator": code, "iso3": iso})
    except Exception:  # noqa: BLE001 — سجل تشخيصي لا شرط تشغيل
        pass


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Silk IMF agent — best-effort IMF WEO (degrades gracefully offline)")
    for m in available_indicators():
        d = imf_indicator("NLD", m, 2023)
        flag = "no-data" if d.value is None else d.value
        print(f"  [{m}] {flag} — {d.note}")
