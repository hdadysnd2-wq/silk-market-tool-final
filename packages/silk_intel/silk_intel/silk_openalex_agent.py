"""وكيل OpenAlex لسِلك — Silk academic/industry literature research tool
(الموجة ٩، V5 — بديل Scopus المجاني).

Scopus يتطلب مفتاحاً مدفوعاً؛ OpenAlex (api.openalex.org) بديل حقيقي مجاني
وبلا مفتاح يغطي نفس الفئة (أدبيات أكاديمية/تجارية مفهرسة، عناوين + سنة +
مصدر + ملخّص + DOI). لا اختلاق: أي فشل (شبكة/تنسيق/نتائج فارغة) يعيد
DataPoint(value=None, confidence=0.0) موسوماً بالسبب.

تصميم الواجهة يسمح ببديل أغنى لاحقاً (Scopus/Elsevier بمفتاح) بلا تغيير
المستدعين: `literature_search()` هي نقطة الدخول الوحيدة؛ إن أُضيف
SCOPUS_API_KEY مستقبلاً، تتحول داخلياً لمصدر أغنى بنفس التوقيع والمخرجات —
لا شيء غير ذلك يتغيّر في `silk_llm_runtime`/`silk_missions`.
"""
from __future__ import annotations

import logging

import requests

from silk_data_layer import DataPoint, _today

log = logging.getLogger(__name__)

_ENDPOINT = "https://api.openalex.org/works"
_TIMEOUT = 20
# OpenAlex "polite pool" — بريد تعريفي يرفع حدّ المعدّل ويقلّل الحجب (توثيق
# OpenAlex الرسمي)؛ لا يتطلب تسجيلاً ولا مفتاحاً، مجرّد ترويسة تعريفية.
_HEADERS = {"User-Agent": "SilkMarketIntel/1.0 (mailto:research@silk.local)"}


def _reconstruct_abstract(inv_index: dict | None, max_len: int = 400) -> str:
    """أعد بناء نص الملخّص من فهرس OpenAlex المعكوس (كلمة → مواضعها) — تنسيق
    OpenAlex القياسي (لا يُخزَّن النص المتصل مباشرة لأسباب حقوق نشر)."""
    if not inv_index or not isinstance(inv_index, dict):
        return ""
    positions: dict[int, str] = {}
    for word, idxs in inv_index.items():
        if not isinstance(idxs, list):
            continue
        for i in idxs:
            if isinstance(i, int):
                positions[i] = word
    if not positions:
        return ""
    ordered = [positions[i] for i in sorted(positions)]
    text = " ".join(ordered)
    return text[:max_len] + ("…" if len(text) > max_len else "")


def openalex_search(query: str, max_records: int = 5) -> list[DataPoint]:
    """ابحث في OpenAlex — literature search, keyless, real results only.

    Returns DataPoint(value={"title","year","venue","abstract_snippet","doi"})
    per work on success, or a single DataPoint(value=None, confidence=0.0) on
    an empty query / network failure / no results — never invents a paper.
    """
    q = (query or "").strip()
    if not q:
        return [DataPoint(None, "OpenAlex", 0.0, "استعلام فارغ — لا بحث",
                          _today())]
    n = max(1, min(int(max_records or 5), 25))
    params = {"search": q, "per_page": str(n)}
    try:
        resp = requests.get(_ENDPOINT, params=params, headers=_HEADERS,
                            timeout=_TIMEOUT)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:  # noqa: BLE001 — لا رفع للمستدعي أبداً
        note = f"OpenAlex fetch failed for {q!r}: {type(e).__name__}: {e}"
        log.warning(note)
        try:  # عائلة C (Wave 1.5): إعلان الفشل للمشغّل.
            import silk_ops_log
            silk_ops_log.record_service_failure("openalex", note)
        except Exception:  # noqa: BLE001
            pass
        return [DataPoint(None, "OpenAlex", 0.0, note, _today())]

    results = payload.get("results") if isinstance(payload, dict) else None
    if not results:
        return [DataPoint(None, "OpenAlex", 0.0,
                          f"no literature results for {q!r}", _today())]

    out: list[DataPoint] = []
    for w in results[:n]:
        title = (w.get("title") or "").strip()
        if not title:
            continue
        venue = (((w.get("primary_location") or {}).get("source") or {})
                .get("display_name") or "")
        out.append(DataPoint(
            {"title": title, "year": w.get("publication_year"),
             "venue": venue,
             "abstract_snippet": _reconstruct_abstract(
                 w.get("abstract_inverted_index")),
             "doi": w.get("doi") or ""},
            "OpenAlex", 0.6, f"literature match for {q!r}", _today()))
    if not out:
        return [DataPoint(None, "OpenAlex", 0.0,
                          f"results returned but none carried a title for "
                          f"{q!r}", _today())]
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    res = openalex_search("halal food consumer market Netherlands", max_records=3)
    for dp in res:
        print(f"  [{dp.confidence}] {dp.value if dp.value is None else dp.value.get('title')}")
