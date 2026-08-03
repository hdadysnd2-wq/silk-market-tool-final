"""تقادُم البيانات من المصدر لا من النثر — provenance-based staleness (القاعدة العامة).

> **قرار المالك (يستبدل نهج «الوسم بالتعبير النمطي أولاً»).** التقادُم يُقرَّر
> **عند الحقيقة** لا بتحليل الجُمَل العربية: كل `DataPoint` يحمل سنة بياناته
> (صراحةً، أو عبر وسم `year=YYYY` البنيوي في الملاحظة كما يكتبه جامع البنك
> الدولي `silk_data_layer.py`، أو من `retrieved_at`). سنةٌ ≤ (السنة الحالية −
> `SILK_STALE_DATA_YEARS`، افتراضياً ٥) => الحقيقة **مُتقادِمة**، فتُوسَم
> «بيانات {السنة} — الأحدث المتاح» **قبل الكتابة** ويحملها الكاتب، وتتحقّق طبقة
> العرض من بقاء الوسم بمقارنة التقرير بـ**قائمة الحقائق المتقادِمة**، لا بإعادة
> تحليل النثر. التعبير النمطي يبقى **شبكة أمان أخيرة فقط**.
>
> **يقتل عائلة العيب دفعةً واحدة** (مراجعة الشيفرة #1/#2/#3/#5): «الطعام 2013»
> لا يُوسَم زوراً (لا حقيقة متقادِمة خلفه)، و«في 2013»/«2013م»/أيّ صياغة
> مستقبلية لا تفلت (الحقيقة نفسها مُعلَّمة مهما كانت الصياغة)، ورمز HS مثل
> 2008 لا يُوسَم (رمزٌ لا سنةَ حقيقة).

المكتبات: stdlib فقط — يستورده جامع الحقائق (الكاتب) وطبقة العرض بلا شبكة.
"""
from __future__ import annotations

import datetime
import os
import re

# وسم السنة البنيوي الذي يكتبه الجامعون في الملاحظة («… year=2013») — البنك
# الدولي (`silk_data_layer._world_bank_for_year`) وكومتريد (`silk_llm_runtime.
# _tool_comtrade_imports`). استخلاصٌ من حقلٍ بنيويّ لا من نثرٍ عربيّ.
_YEAR_MARKER_RE = re.compile(r"\byear\s*=\s*(\d{4})\b")
# سنة تاريخِ رصدٍ في retrieved_at — أيّ «YYYY-MM-DD» (مراجعة الشيفرة #3: لا
# تُقيَّد بنهاية السنة). تمييزُ طابع الجلب عن سنة البيانات يتمّ في fact_year
# بإشارةِ «السنة الماضية» (طابع `_today()` = السنة الجارية => ليس فِنتيج).
_OBS_YEAR_RE = re.compile(r"^\s*(\d{4})-\d{2}-\d{2}\b")

STALE_TAG = "الأحدث المتاح"


def stale_years_back() -> int:
    """نافذة التقادُم بالسنوات — SILK_STALE_DATA_YEARS (٥ افتراضياً)."""
    try:
        n = int(os.environ.get("SILK_STALE_DATA_YEARS", "5"))
        return n if n > 0 else 5
    except (TypeError, ValueError):
        return 5


def stale_threshold_year() -> int:
    """أحدث سنةٍ تُعتبَر «متقادِمة» — (السنة الحالية − النافذة)."""
    return datetime.date.today().year - stale_years_back()


def _get(dp: object, key: str) -> object:
    """اقرأ حقلاً من DataPoint (كائن) أو dict خام."""
    if isinstance(dp, dict):
        return dp.get(key)
    return getattr(dp, key, None)


def fact_year(dp: object) -> int | None:
    """سنة بيانات الحقيقة من مصدرها البنيوي — لا تحليل نثر (الدرس ٣٣):
    (١) **الحقل البنيويّ `data_year`** الذي يضبطه الجامعون (المصدر المُعتمَد)،
    (٢) `year=YYYY` في الملاحظة (**احتياط قديم** لمدوّنات مخزّنة قبل الحقل — لم
    يعد يُكتَب)، (٣) سنة `retrieved_at` كتاريخِ رصدٍ (أيّ YYYY-MM-DD) **إن كانت
    سنةً ماضية** لا طابعَ جلبٍ للسنة الجارية (مراجعة #3: يقبل غير نهاية السنة،
    ويستبعد طابع الجلب بإشارةِ «السنة الماضية»). None إن تعذّر."""
    for k in ("data_year", "year"):
        v = _get(dp, k)
        if isinstance(v, bool):
            continue
        if isinstance(v, int) and 1900 <= v <= 2100:
            return v
        if isinstance(v, str) and v.strip().isdigit() and len(v.strip()) == 4:
            return int(v)
    note = str(_get(dp, "note") or "")
    m = _YEAR_MARKER_RE.search(note)  # احتياط قديم لا يُكتَب بعد اليوم
    if m:
        return int(m.group(1))
    ra = str(_get(dp, "retrieved_at") or "")
    m = _OBS_YEAR_RE.match(ra)
    if m:
        y = int(m.group(1))
        # السنة الجارية = طابع جلبٍ (`_today()`) لا سنةَ بيانات؛ الماضية = رصد.
        if y < datetime.date.today().year:
            return y
    return None


def is_stale_year(year: object, back: int | None = None) -> bool:
    """هل السنة متقادِمة؟ — year ≤ (الحالية − النافذة). None => False."""
    if year is None:
        return False
    try:
        y = int(year)
    except (TypeError, ValueError):
        return False
    thr = datetime.date.today().year - (back if back and back > 0
                                        else stale_years_back())
    return y <= thr


def stale_tag(year: object) -> str:
    """نصّ الإفصاح الموحّد — «بيانات {السنة} — الأحدث المتاح»."""
    return f"بيانات {year} — {STALE_TAG}"


def is_stale_fact(dp: object) -> bool:
    """حقيقةٌ حاملةٌ قيمةً فعلية وسنتُها متقادِمة (فجوة None ليست رقماً)."""
    if _get(dp, "value") is None:
        return False
    return is_stale_year(fact_year(dp))


def stale_fact_years(findings: object) -> set[int]:
    """مجموعة سنوات الحقائق المتقادِمة (ذات القيم) — قائمة الحقيقة المتقادِمة
    التي تقارن بها طبقةُ العرض التقريرَ (لا تحليل نثر)."""
    out: set[int] = set()
    for f in findings or []:
        if _get(f, "value") is None:
            continue
        y = fact_year(f)
        if y is not None and is_stale_year(y):
            out.add(int(y))
    return out
