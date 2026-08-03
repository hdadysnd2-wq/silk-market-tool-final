"""استشارات ما قبل التشغيل — عائلة «الدراسة بالاتجاه الخاطئ» (Wave 1.5, family A).

استشارةُ بلد المنشأ (Wave 1) عضوٌ واحدٌ في عائلةٍ أوسع: **دراسةُ دخولِ سوقٍ لا
معنى لدراسته**. هذه الوحدة تُعمّم العائلة بأشقّاء إضافيين — كلّهم **مبنيّون على
البيانات، config-driven، بلا أيّ قائمة مكتوبة صلبًا في الشيفرة**، وبلا نداءٍ
مدفوع:

- **`self_origin`**: السوق المستهدفة هي بلد المنشأ نفسه (تصدير إلى نفسك). بلدُ
  المنشأ من البيئة (`SILK_ORIGIN_ISO3`، افتراضيًا SAU) — لا رمز دولة مكتوب صلبًا.
- **`sanction`**: السوق تحت حظر/عقوبات وفق مرجعٍ يصونه المالك
  (`data/restricted_markets.csv`، صفٌّ بلا `hs_prefix`).
- **`restricted_chapter`**: فصل HS للمنتج مقيَّد/محظور قانونيًا في السوق (لحوم
  خنزير/مشروبات روحية → الخليج مثلًا) وفق نفس المرجع (صفٌّ بـ`hs_prefix`).

عقد عدم الاختلاق: المرجعُ ملفٌّ بيانات يصونه المالك (كالمدوّنة القانونية) — لا
تُخترَع قيود، والملف الغائب/الفارغ => لا استشارة (فشلٌ آمن مفتوح). القاعدة تُعمَّم
من البيانات لا من الأسماء؛ القفل `test_wave1p5_prerun_advisories.py` يثبت خلوّ
المنطق من أيّ رمز دولة/HS مكتوب صلبًا (عائلة `hardcoded-product-rule`).
"""
from __future__ import annotations

import csv
import functools
import logging
import os

log = logging.getLogger("silk.prerun")

_HERE = os.path.dirname(os.path.abspath(__file__))
_RESTRICTED_CSV = os.path.join(_HERE, "data", "restricted_markets.csv")


def origin_iso3() -> str:
    """بلدُ منشأ المنصّة — config-driven (`SILK_ORIGIN_ISO3`, افتراضيًا SAU)."""
    return (os.environ.get("SILK_ORIGIN_ISO3", "SAU").strip().upper() or "SAU")


def advisories_enabled() -> bool:
    """صمّام أشقّاء العائلة (Wave 1.5) — SILK_PRERUN_ADVISORIES=1 (افتراضي مُطفأ
    => السلوك كاليوم: استشارةُ بلد المنشأ وحدها من Wave 1 تبقى كما هي)."""
    return os.environ.get("SILK_PRERUN_ADVISORIES", "0").strip() == "1"


@functools.lru_cache(maxsize=1)
def _load_restricted() -> list[dict]:
    """اقرأ مرجع القيود — owner-maintained CSV. غائب/تالف => [] (فشل آمن مفتوح).

    يقرأ المسار من الثابت وقت النداء (لا افتراضًا مربوطًا وقت التعريف) كي
    تعمل العزلة الاختبارية؛ مُخبّأ (يُمسَح بـ`cache_clear` عند تغيّر المسار)."""
    path = _RESTRICTED_CSV
    try:
        with open(path, newline="", encoding="utf-8") as f:
            return [r for r in csv.DictReader(f)
                    if (r.get("market_iso3") or "").strip()]
    except Exception as exc:  # noqa: BLE001 — مرجعٌ اختياري، لا يكسر المسار
        log.warning("restricted_markets load failed (%s): %s", path, exc)
        return []


def _restricted_hits(hs_code, market_iso3: str) -> list[dict]:
    """صفوفُ المرجع المطابقة لهذه (السوق، رمز HS) — sanctions + restricted chapters."""
    iso3 = (market_iso3 or "").strip().upper()
    hs = "".join(ch for ch in str(hs_code or "") if ch.isdigit())
    out: list[dict] = []
    for row in _load_restricted():
        if (row.get("market_iso3") or "").strip().upper() != iso3:
            continue
        prefix = "".join(ch for ch in str(row.get("hs_prefix") or "")
                         if ch.isdigit())
        kind = (row.get("kind") or "").strip() or "restricted_chapter"
        if not prefix:                       # صفٌّ بلا رمز => قيدُ سوقٍ كامل (عقوبات)
            out.append({"kind": kind or "sanction",
                        "reason_ar": row.get("reason_ar") or "",
                        "source_url": row.get("source_url") or ""})
        elif hs and hs.startswith(prefix):   # فصلٌ مقيَّد لهذا المنتج في هذه السوق
            out.append({"kind": "restricted_chapter",
                        "reason_ar": row.get("reason_ar") or "",
                        "source_url": row.get("source_url") or "",
                        "hs_prefix": prefix})
    return out


def sibling_advisories(hs_code, market_iso3: str) -> list[dict]:
    """أشقّاء عائلة A لهذه (السوق، رمز HS) — a list of advisory dicts, or [].

    كلٌّ `{kind, message, detail}`؛ الاستشارةُ تحذيرٌ يتطلّب موافقةً صريحة (لا
    حجب نهائي). صفر نداء مدفوع، config-driven. لا تشمل استشارةَ بلد المنشأ
    (Wave 1، تبقى في بوّابة api كما هي) — هذه أشقّاؤها الجدد فقط.
    """
    iso3 = (market_iso3 or "").strip().upper()
    out: list[dict] = []
    if len(iso3) != 3:
        return out
    # (i) تصدير إلى بلد المنشأ نفسه — لا معنى لدراسة دخول سوقك.
    if iso3 == origin_iso3():
        out.append({
            "kind": "self_origin",
            "message": "⚠ السوق المستهدفة هي بلد المنشأ نفسه — لا معنى لدراسة "
                       "«دخول» سوقك المحلي. أكمل؟",
            "detail": f"origin={origin_iso3()}"})
    # (ii)+(iii) عقوبات / فصل مقيَّد — من مرجع المالك (config-driven).
    for hit in _restricted_hits(hs_code, iso3):
        if hit["kind"] == "sanction":
            out.append({
                "kind": "sanction",
                "message": "⚠ هذه السوق تحت حظر/عقوبات وفق مرجع القيود — "
                           "دراسة دخولها قد تكون غير قابلة للتنفيذ. أكمل؟",
                "detail": hit.get("reason_ar") or ""})
        else:
            out.append({
                "kind": "restricted_chapter",
                "message": "⚠ فئة هذا المنتج مقيَّدة/محظورة قانونيًا في السوق "
                           "المستهدفة — تحقّق قبل المتابعة. أكمل؟",
                "detail": hit.get("reason_ar") or ""})
    return out
