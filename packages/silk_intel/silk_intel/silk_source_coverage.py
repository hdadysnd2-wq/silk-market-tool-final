"""تغطية المصادر ووسم «تقدير استرشادي» — Master Prompt Part 2 §D.

كل مؤشرٍ في التقرير المُسلَّم إما: (١) مصدرٌ عموميٌّ مسمّى + تاريخ رصدٍ، أو
(٢) وسمُ «تقدير استرشادي» صريح عند نقطة الاستعمال (لا حاشية وحدها). لا عمود
مصدرٍ عارٍ («—») بلا أحد الخيارين. عتبة قبول: ≥٨٥٪ من المؤشرات بمصدرٍ مسمّى
حقيقي؛ دون ذلك، ضيّق نطاق التقرير وأعلن الفجوة بدل شحن مؤشرات بلا مصدر.

منطق صرف: صفر شبكة، قراءة CSV محلي فقط — نفس نمط `data/requirements_l1.csv`.
"""
from __future__ import annotations

import csv
import os

# وسم «تقدير استرشادي» — يظهر عند **نقطة استعمال** الرقم المُقدَّر (لا في
# حاشية فقط)، مصحوباً بسطر اشتقاق واحد وفرضياته (Master Prompt Part 2، البند ١٢).
INDICATIVE_ESTIMATE_TAG = "تقدير استرشادي"

# قيم مصدرٍ تُعامَل كغيابٍ فعلي — «—» العارية ممنوعة، ووسم التقدير الصريح هو
# البديل الوحيد المقبول (لا صمتٌ ولا اختلاق).
_BLANK_SOURCE_TOKENS = frozenset({
    "", "-", "—", "–", "none", "null", "n/a", "na", "unknown",
    "غير معروف", "غير محدد", "غير متاح", "غير متوفر"})

SOURCE_COVERAGE_MIN_PCT = 85.0

_FAMILY_SOURCES_CSV = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data",
    "default_sources_by_family.csv")

_cache: "dict[str, list[dict]] | None" = None


def tag_indicative_estimate(value_text: str, derivation: str) -> str:
    """ألصق وسم «تقدير استرشادي» + سطر اشتقاقٍ واحد عند نقطة استعمال رقمٍ
    مُقدَّر — لا حاشيةٌ منفصلة (Master Prompt Part 2، البند ١٢)."""
    v = str(value_text or "").strip()
    d = str(derivation or "").strip()
    if not d:
        return f"{v} ({INDICATIVE_ESTIMATE_TAG})"
    return f"{v} ({INDICATIVE_ESTIMATE_TAG} — {d})"


def _load_family_sources() -> "dict[str, list[dict]]":
    """مراجع المصادر الافتراضية لكل عائلة منتج (غذاء/نسيج/كيماويات/آلات) —
    مرجعٌ ثابتٌ (كـ`data/requirements_l1.csv`) يُعامَل بحذر: أضِف مصدراً
    برابطه الرسمي الحقيقي فقط، لا رابطاً مختلَقاً."""
    global _cache
    if _cache is not None:
        return _cache
    out: "dict[str, list[dict]]" = {}
    try:
        with open(_FAMILY_SOURCES_CSV, encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                fam = (row.get("family") or "").strip().lower()
                if not fam:
                    continue
                out.setdefault(fam, []).append({
                    "source_name": row.get("source_name") or "",
                    "url": row.get("url") or "",
                    "scope": row.get("scope") or ""})
    except OSError:
        out = {}
    _cache = out
    return out


def default_sources_for_family(family: str) -> list[dict]:
    """قائمة المصادر الافتراضية المسمّاة لعائلة منتجٍ (food/textiles/
    chemicals/machinery) — قائمةٌ فارغة لعائلةٍ غير معروفة (لا اختلاق)."""
    return list(_load_family_sources().get(str(family or "").strip().lower(), []))


def known_product_families() -> list[str]:
    return sorted(_load_family_sources().keys())


def _is_backed(source: object, note: object) -> bool:
    src = str(source or "").strip().lower()
    if src and src not in _BLANK_SOURCE_TOKENS:
        return True
    return INDICATIVE_ESTIMATE_TAG in str(note or "")


def compute_source_coverage(dr: dict) -> dict:
    """نسبة المؤشرات (DataPoint بقيمةٍ فعلية `value is not None`) التي تحمل
    مصدراً مسمّى حقيقياً أو وسم «تقدير استرشادي» صريح — Master Prompt Part 2
    §D. فجواتٌ معلنة (`value=None`) ليست مؤشراتٍ مُسلَّمة فلا تُحتسَب."""
    total = 0
    backed = 0
    for m in (dr.get("missions") or {}).values():
        for f in (m.get("findings") or []):
            if f.get("value") is None:
                continue
            total += 1
            if _is_backed(f.get("source"), f.get("note")):
                backed += 1
    pct = (backed / total * 100.0) if total else 100.0
    return {"total": total, "backed": backed, "pct": pct}
