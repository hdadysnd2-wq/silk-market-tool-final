"""عميل مكشطة خرائط قوقل — Google Maps scraper client (C1، أمر العمل الرئيس).

المكشطة (`gosom/google-maps-scraper`) تُنشَر **خدمة Railway ثانية** بشبكة
خاصة، لا تُضمَّن في حاوية بايثون — عزلٌ للمخاطرة: إن حجبها قوقل أو تعطّلت،
التطبيق الرئيس والقواعد والمهام سليمة تماماً. عنوانها الداخلي يُمرَّر
بمتغيّر واحد `SILK_GMAPS_SCRAPER_URL`.

**التعطيل النظيف (clean-disable):** غياب المتغيّر = تعطيل كامل — لا نداء
يُحاوَل، ولا أثر على `/health` الرئيس ولا على جهوزية البحث (`research_ready`).
حالة المكشطة في `/health` إخبارية فقط، لا تحجب شيئاً.

هذا الملف واجهة **التهيئة والتعطيل النظيف فقط (C1)**. منطق تقديم مهمة الكشط
وتحليل النتائج والسلسلة الاحتياطية (C2–C5) لا يُفتَح إلا بعد أن يؤكّد المالك
أن الخدمة الثانية حيّة على Railway (قرار D-03: كلود لا يستطيع تزويد Railway،
فأمرٌ لا يستطيع إغلاق نفسه بنفسه ليس أمراً).
"""
from __future__ import annotations

import os
import re

ENV_VAR = "SILK_GMAPS_SCRAPER_URL"


def scraper_url() -> str:
    """عنوان خدمة المكشطة الداخلي (شبكة Railway الخاصة) أو "" إن لم يُضبَط."""
    return os.environ.get(ENV_VAR, "").strip()


def enabled() -> bool:
    """هل المكشطة مُهيَّأة؟ غيابها تعطيل نظيف — لا نداء يُحاوَل، لا كسر."""
    return bool(scraper_url())


def health_status() -> str:
    """سطر حالة إخباري لـ`/health` — لا يحجب جهوزية البحث ولا يكشف العنوان
    الداخلي (لا تسريب اسم مضيف خاص)."""
    if enabled():
        return "on — مُهيَّأة (شبكة خاصة، خدمة منفصلة)"
    return (f"off — {ENV_VAR} غائب (المكشطة معطّلة تعطيلاً نظيفاً — "
            "لا أثر على المهام أو جهوزية البحث)")


# ═══════════════════════════════════════════════════════════════════════════
# C2–C5 (SPEC-v2, Command #5b): تقديم مهمة الكشط، الاستطلاع، التحليل،
# السلسلة الاحتياطية، والتخزين المؤقت — كلّه معزول هنا خلف التعطيل النظيف.
# عقد عدم الاختلاق مقدَّس: أيّ فشل شبكة/خدمة = فجوة معلنة ([], path='gap')،
# لا صف مختلَق ولا رقم مخترَع. المكشطة تعطي هاتفاً وإيميلاً؛ Places الرسمي
# (السلسلة الاحتياطية) يعطي اسماً/عنواناً/تقييماً بلا إيميل — كل صف يحمل
# مستوى توثيقه الصادق.
# ═══════════════════════════════════════════════════════════════════════════
import concurrent.futures as _cf  # noqa: E402
import hashlib as _hashlib  # noqa: E402
import json as _json  # noqa: E402
import logging as _logging  # noqa: E402
import time as _time  # noqa: E402

_log = _logging.getLogger(__name__)

# D-02: الكشط غير متزامن ولا يُحتسب في ميزانية العشر دقائق؛ مهلة صلبة ٨ دقائق
# (يمكن ضبطها) — إن لم يعُد، نسقط للسلسلة الاحتياطية ونعلن الفجوة. التشغيلة
# لا تنتظره أبداً (تُقدَّم مبكراً وتُجمَع بمهلة محدودة بعد البعثات).
_HARD_TIMEOUT_S = int(os.environ.get("SILK_GMAPS_TIMEOUT_SECONDS", "480"))
_POLL_INTERVAL_S = int(os.environ.get("SILK_GMAPS_POLL_SECONDS", "10"))
_SUBMIT_TIMEOUT_S = 15
_HTTP_TIMEOUT_S = 20
_TOP_N = 15                       # C3: أعلى ~١٥ رائداً بعد إزالة التكرار
_LEADS_TTL_S = 7 * 86400          # C3: تخزين مؤقت للروابط لكل (سوق، مجموعة استعلام)

_MAPS_DOC_LEVEL = "◐ مرصود عبر خرائط قوقل"
_WEB_DOC_LEVEL = "○ مرشّح ويب غير موثَّق"
# C5: سطر صريح — قائمة الخرائط تثبت وجود النشاط وجهةَ اتصاله، لا أنه يستورد
# **المنتج المدروس** فعلاً (لا مبالغة في دلالة الرصد). Wave 2 (البند ١٠): كان
# «التمور السعودية» مثبَّتًا صلبًا في تقرير أيّ منتج — بارامتري الآن بالمنتج
# المدروس. القفل: `test_wave2_first_pdf_cluster.py` بمنتجٍ غير التمور.
def maps_disclaimer(product: str = "") -> str:
    """سطر إخلاء المسؤولية لجدول الخرائط، مُشتقٌّ من المنتج المدروس (لا مثبَّت)."""
    prod = (product or "").strip()
    tail = (f"لا أنه يستورد «{prod}»" if prod
            else "لا أنه يستورد المنتج المدروس")
    return ("إدراج النشاط في خرائط قوقل يثبت وجوده وجهة اتصاله فقط، "
            + tail + " — التحقق التجاري خطوة تالية.")


# توافق رجعي: ثابتٌ عامّ بلا أيّ اسم منتج مثبَّت (لا «التمور السعودية»).
MAPS_DISCLAIMER = maps_disclaimer("")

# C2: مصطلحات المستورد/الجملة بلغة السوق (أرضية توضيحية موسَّعة، لا سقف).
_LOCALIZED_IMPORTER_TERMS = {
    "nl": ["importeur", "groothandel", "halal groothandel",
           "arabische supermarkt groothandel"],
    "de": ["importeur", "großhandel", "halal großhandel",
           "arabischer supermarkt großhandel"],
    "fr": ["importateur", "grossiste", "grossiste halal",
           "épicerie arabe grossiste"],
    "es": ["importador", "mayorista", "mayorista halal",
           "supermercado árabe mayorista"],
    "ar": ["مستورد", "تاجر جملة", "جملة حلال", "سوبر ماركت عربي جملة"],
    "en": ["importer", "wholesale distributor", "halal wholesale",
           "ethnic supermarket wholesale"],
}
# ترجمة المنتج الأساسي للغة السوق — يحسّن دقة الاستعلام (تمور→dadels بالهولندية).
_PRODUCT_LOCALE = {
    "nl": "dadels", "de": "datteln", "fr": "dattes", "es": "dátiles",
    "en": "dates", "ar": "تمر",
}
_DATES_ALIASES = {"تمور", "تمر", "dates", "date"}


def _market_lang(market_ref) -> str:
    """اللغة الأساسية للسوق من market_locale.csv (lang_primary) أو 'en'."""
    iso3 = (getattr(market_ref, "iso3", "") or "").upper()
    if not iso3:
        return "en"
    try:
        import csv
        path = os.path.join(os.path.dirname(__file__), "data", "market_locale.csv")
        with open(path, encoding="utf-8") as fh:
            for row in csv.DictReader(r for r in fh if not r.startswith("#")):
                if (row.get("iso3") or "").upper() == iso3:
                    return (row.get("lang_primary") or "en").strip() or "en"
    except Exception:  # noqa: BLE001 — تعذّر القراءة = افتراضي إنجليزي، لا كسر
        pass
    return "en"


def localized_queries(product: str, market_ref) -> list:
    """C2: مجموعة استعلامات بلغة السوق (مستورد/جملة/جملة حلال/سوبر ماركت
    إثني) — لا تخمين، لغة السوق الفعلية من market_locale."""
    lang = _market_lang(market_ref)
    terms = _LOCALIZED_IMPORTER_TERMS.get(lang, _LOCALIZED_IMPORTER_TERMS["en"])
    country = (getattr(market_ref, "name_en", "") or "").strip().lower()
    prod = (product or "").strip()
    if prod.lower() in _DATES_ALIASES or prod in _DATES_ALIASES:
        prod = _PRODUCT_LOCALE.get(lang, prod)
    return [f"{prod} {terms[0]} {country}".strip(),
            f"{prod} {terms[1]}".strip(),
            f"{terms[2]} {country}".strip(),
            terms[3]]


def submit_scrape(queries: list, depth: int = 1, extract_email: bool = True):
    """C2: قدّم مهمة كشط واحدة (POST) — يعيد معرّف المهمة أو None عند أي فشل
    (تعطيل نظيف). لا ينتظر النتائج. واجهة gosom web-mode المفترَضة:
    POST {url}/api/v1/jobs — راجع docs/DEPLOY_SCRAPER.md لتأكيد الشكل."""
    url = scraper_url()
    if not url or not queries:
        return None
    try:
        import requests
        body = {"name": "silk-importers", "keywords": list(queries),
                "depth": int(depth), "email": bool(extract_email),
                "max_time": f"{_HARD_TIMEOUT_S}s"}
        r = requests.post(f"{url.rstrip('/')}/api/v1/jobs", json=body,
                          timeout=_SUBMIT_TIMEOUT_S)
        r.raise_for_status()
        jid = (r.json() or {}).get("id")
        _log.info("gmaps scrape job submitted: %s (%d queries)", jid, len(queries))
        return jid or None
    except Exception as e:  # noqa: BLE001 — فشل التقديم = تعطيل نظيف
        _log.warning("gmaps submit failed: %s", e)
        # عائلة C (Wave 1.5): لا فشلٌ صامت — أعلِنه للمشغّل في ops_errors مع
        # أنّ المكشطة كانت **مُهيَّأة** (URL مضبوط) لكنّ النداء فشل، فيُميَّز
        # «معطّلة عمدًا» (لا URL) من «مُهيَّأة لكن فشلت» (البلاغ الأصلي).
        try:
            import silk_ops_log
            silk_ops_log.record_service_failure(
                "scraper", f"تقديم مهمة الكشط فشل رغم تهيئة المكشطة: {e}",
                context={"stage": "submit", "queries": len(queries or [])})
        except Exception:  # noqa: BLE001 — السجل قناة جانبية، لا يكسر التعطيل
            pass
        return None


def _fetch_job(job_id: str):
    """اجلب حالة/نتائج المهمة — (status, raw_results|None). None عند الفشل."""
    url = scraper_url()
    try:
        import requests
        r = requests.get(f"{url.rstrip('/')}/api/v1/jobs/{job_id}",
                         timeout=_HTTP_TIMEOUT_S)
        r.raise_for_status()
        j = r.json() or {}
        status = str(j.get("status") or "").lower()
        results = j.get("results") or j.get("data")
        if results is None and status in ("ok", "done", "completed", "finished"):
            # بعض النسخ تُنزِّل النتائج على مسار منفصل.
            rd = requests.get(f"{url.rstrip('/')}/api/v1/jobs/{job_id}/download",
                              timeout=_HTTP_TIMEOUT_S)
            if rd.ok:
                results = rd.json()
        return status, results
    except Exception as e:  # noqa: BLE001
        _log.warning("gmaps fetch job %s failed: %s", job_id, e)
        try:
            import silk_ops_log
            silk_ops_log.record_service_failure(
                "scraper", f"جلب نتائج مهمة الكشط فشل: {e}",
                context={"stage": "fetch", "job_id": job_id})
        except Exception:  # noqa: BLE001
            pass
        return None, None


def poll_leads(job_id: str, deadline_monotonic: float):
    """C2: استطلع حتى تكتمل المهمة أو تبلغ المهلة الصلبة — يعيد نتائج خاماً
    أو None (مهلة/فشل = None، تُترجَم لفجوة/احتياط لاحقاً)."""
    if not job_id:
        return None
    while _time.monotonic() < deadline_monotonic:
        status, results = _fetch_job(job_id)
        if status is None:
            return None  # فشل شبكة صريح
        if results is not None and status in (
                "ok", "done", "completed", "finished"):
            return results
        if status in ("failed", "error", "cancelled"):
            return None
        _time.sleep(min(_POLL_INTERVAL_S,
                        max(0.0, deadline_monotonic - _time.monotonic())))
    return None  # مهلة صلبة بلغت (D-02) — لا انتظار أبعد


def _s(v) -> str:
    return str(v).strip() if v is not None else ""


def _parse_lead(raw: dict) -> dict:
    """C3: طبّع صفّاً واحداً لحقول ثابتة — يتحمّل تعدّد أسماء الحقول عبر
    نسخ المكشطة. لا يخترع قيمة: الحقل الغائب يبقى ''."""
    if not isinstance(raw, dict):
        return {}
    emails = raw.get("emails") or raw.get("email") or ""
    if isinstance(emails, list):
        emails = emails[0] if emails else ""
    return {
        "name": _s(raw.get("title") or raw.get("name")),
        "address": _s(raw.get("address") or raw.get("full_address")
                      or raw.get("formatted_address")),
        "phone": _s(raw.get("phone") or raw.get("phone_number")),
        "email": _s(emails),
        "website": _s(raw.get("website") or raw.get("web_site")),
        "rating": raw.get("rating") if isinstance(
            raw.get("rating"), (int, float)) else None,
        "review_count": (raw.get("review_count") or raw.get("reviews")
                         or raw.get("user_ratings_total")),
        "maps_link": _s(raw.get("link") or raw.get("google_maps_url")
                        or raw.get("url")),
        "doc_level": _MAPS_DOC_LEVEL,
        "source": "google_maps_scraper",
    }


def _dedupe(leads: list) -> list:
    """أزِل التكرار على (الاسم المُطبَّع + أول جزء من العنوان) — يبقي الأغنى."""
    seen: dict = {}
    for lead in leads:
        name = (lead.get("name") or "").strip().lower()
        if not name:
            continue
        key = name + "|" + (lead.get("address") or "")[:20].lower()
        prev = seen.get(key)
        if prev is None or _lead_richness(lead) > _lead_richness(prev):
            seen[key] = lead
    return list(seen.values())


def _lead_richness(lead: dict) -> int:
    return sum(1 for k in ("phone", "email", "website", "maps_link")
               if lead.get(k))


def parse_and_rank(raw_results) -> list:
    """C3: خام → مُطبَّع → مُزال التكرار → أعلى ~١٥. [] إن لا نتائج."""
    if not raw_results:
        return []
    rows = raw_results if isinstance(raw_results, list) else [raw_results]
    parsed = [p for p in (_parse_lead(r) for r in rows) if p.get("name")]
    parsed = _dedupe(parsed)
    parsed.sort(key=lambda l: (_lead_richness(l),
                               l.get("rating") or 0,
                               l.get("review_count") or 0), reverse=True)
    return parsed[:_TOP_N]


# ── التخزين المؤقت للروابط لكل (سوق، مجموعة استعلام) — C3 ────────────────────
def _cache_path(iso3: str, queries: list) -> str:
    import silk_cache
    h = _hashlib.sha1(("|".join(sorted(queries))).encode("utf-8")).hexdigest()[:16]
    return os.path.join(silk_cache._cache_dir(), f"gmaps_leads_{iso3}_{h}.json")


def cache_get(iso3: str, queries: list):
    path = _cache_path(iso3, queries)
    try:
        if _time.time() - os.path.getmtime(path) < _LEADS_TTL_S:
            with open(path, encoding="utf-8") as fh:
                return _json.load(fh)
    except (OSError, ValueError):
        return None
    return None


def cache_put(iso3: str, queries: list, leads: list) -> None:
    try:
        with open(_cache_path(iso3, queries), "w", encoding="utf-8") as fh:
            _json.dump(leads, fh, ensure_ascii=False)
    except OSError as e:  # noqa: BLE001 — التخزين تحسين لا شرط
        _log.warning("gmaps leads cache write failed: %s", e)


# ── السلسلة الاحتياطية (C4): المكشطة → Places الرسمي → فجوة معلنة ────────────
def places_fallback(product: str, market_ref) -> list:
    """C4: المكشطة سقطت/فارغة ⇒ Places الرسمي (المفتاح غير المستعمَل يكسب
    قيمته): اسم/عنوان/تقييم — بلا إيميل. [] إن فشل أيضاً (⇒ فجوة معلنة)."""
    try:
        from silk_maps_agent import find_places
    except Exception:  # noqa: BLE001
        return []
    lang = _market_lang(market_ref)
    terms = _LOCALIZED_IMPORTER_TERMS.get(lang, _LOCALIZED_IMPORTER_TERMS["en"])
    country = (getattr(market_ref, "name_en", "") or "").strip()
    region = (getattr(market_ref, "iso2", "") or "").lower() or None
    out: list = []
    for term in terms[:2]:  # استعلامان يكفيان للاحتياط (حصّة/تكلفة)
        for dp in find_places(f"{product} {term} {country}".strip(), region=region):
            v = getattr(dp, "value", None)
            if not isinstance(v, dict) or not v.get("name"):
                continue
            out.append({
                "name": _s(v.get("name")), "address": _s(v.get("address")),
                "phone": "", "email": "", "website": "",
                "rating": v.get("rating"),
                "review_count": v.get("user_ratings_total"),
                "maps_link": "", "doc_level": _MAPS_DOC_LEVEL,
                "source": "google_places_api"})
    return _dedupe(out)[:_TOP_N]


_MAX_NAME_WORDS = int(os.environ.get("SILK_LEAD_NAME_MAX_WORDS", "8") or "8")
_MAX_NAME_CHARS = int(os.environ.get("SILK_LEAD_NAME_MAX_CHARS", "72") or "72")


def looks_like_name(s: str) -> bool:
    """هل النصّ اسمُ كِيانٍ معقول (شركة/موزّع) لا جملةَ نثرٍ؟ — Wave 2 (البند ٥).

    بلاغ أول PDF: جُملُ بعثاتٍ إنجليزية خام دخلت جدول الروابط كأسماء رواد.
    الرائد يتطلّب **كِيانَ اسمٍ** لا جملة: قصيرٌ (كلمات/أحرف محدودة)، بلا ترقيم
    جملة (`.`/`!`/`؟`/`:`)، وليس عبارةً ابتدائية إنجليزية شائعة. الجملُ تُوجَّه
    للسرد لا للجدول (لا اختلاق، ولا نثرٌ إنجليزيٌّ في خلية عميل).
    """
    n = (s or "").strip()
    if not n:
        return False
    words = n.split()
    if len(words) > _MAX_NAME_WORDS or len(n) > _MAX_NAME_CHARS:
        return False
    if re.search(r"[.!?؟:؛](\s|$)", n) or ". " in n:
        return False
    # عبارةٌ إنجليزية ابتدائية (فعل/أداة) => جملةٌ لا اسم.
    if re.match(r"(?i)^(the |a |an |it |they |this |these |there |we |our |"
                r"is |are |importers? |according )", n):
        return False
    return True


def extract_web_candidates(mission_reports: dict) -> list:
    """C5: أسماء المرشّحين من بحث الويب (بعثة channels_importers) — للمضاهاة
    والدمج مع رواد الخرائط. **كِياناتُ أسماءٍ فقط** (لا جُمل)، غير موثَّقة."""
    names: list = []
    rep = (mission_reports or {}).get("channels_importers")
    for dp in (getattr(rep, "findings", None) or []):
        val = getattr(dp, "value", None)
        cand = ""
        if isinstance(val, str) and val.strip():
            cand = val.strip()
        elif isinstance(val, dict) and val.get("name"):
            cand = str(val["name"]).strip()
        if cand and looks_like_name(cand):     # الجملُ تُرفَض (تُوجَّه للسرد)
            names.append(cand)
    return names


def _merge_web_candidates(leads: list, web_candidates: list) -> list:
    """C5: ضاهِ مرشّحي الويب مع رواد الخرائط بالاسم؛ الاسم غير المطابق يُضاف
    صفّاً بمستوى «مرشّح ويب» (اسم فقط) — لا اختلاق جهة اتصال."""
    if not web_candidates:
        return leads
    have = {(l.get("name") or "").strip().lower() for l in leads}
    merged = list(leads)
    for name in web_candidates:
        n = name.strip()
        low = n.lower()
        if not n or low in have:
            continue
        # مطابقة جزئية متحفّظة: إن كان اسم مرشّح الويب جزءاً من رائد موجود، تخطَّ.
        if any(low in h or h in low for h in have if h):
            continue
        have.add(low)
        merged.append({"name": n, "address": "", "phone": "", "email": "",
                       "website": "", "rating": None, "review_count": None,
                       "maps_link": "", "doc_level": _WEB_DOC_LEVEL,
                       "source": "web_search"})
    return merged[:_TOP_N]


def submit_scrape_async(product: str, market_ref):
    """C2/D-02: قدّم الكشط مبكراً على خيط منفصل ويعيد Future — لا ينتظر.
    None إن كانت المكشطة معطّلة. يُستدعى في بدء التشغيلة (قبل البعثات)."""
    if not enabled():
        return None
    queries = localized_queries(product, market_ref)
    iso3 = (getattr(market_ref, "iso3", "") or "").upper()
    if cache_get(iso3, queries) is not None:
        # روابط مخزّنة — لا حاجة لكشط جديد (C3). Future يعيد علامة «مخزَّن».
        ex = _cf.ThreadPoolExecutor(max_workers=1)
        return ex.submit(lambda: {"_cached": queries})

    def _worker():
        jid = submit_scrape(queries)
        if not jid:
            return None
        deadline = _time.monotonic() + _HARD_TIMEOUT_S
        raw = poll_leads(jid, deadline)
        # C3: خزّن فور الاكتمال حتى لو تخلّى الجامعُ عن الانتظار (مهلة الجمع
        # القصيرة) — إعادة التشغيل القادمة تُعيد استعمالها بلا كشط جديد.
        leads = parse_and_rank(raw)
        if leads:
            cache_put(iso3, queries, leads)
        return raw
    ex = _cf.ThreadPoolExecutor(max_workers=1)
    return ex.submit(_worker)


def finalize_leads(future, product: str, market_ref, web_candidates=None,
                   timeout_s: float = None) -> dict:
    """C2–C5: اجمع نتائج الكشط بمهلة محدودة (لا انتظار أبعد من D-02)، وإلا
    السلسلة الاحتياطية Places، وإلا فجوة معلنة. ثم ادمج مرشّحي الويب،
    خزّن، وأعِد {leads, path, note}. path ∈ {cache,scraper,places,gap}."""
    iso3 = (getattr(market_ref, "iso3", "") or "").upper()
    queries = localized_queries(product, market_ref)
    web_candidates = web_candidates or []
    raw = None
    if future is not None:
        try:
            raw = future.result(timeout=timeout_s if timeout_s is not None
                                else _HARD_TIMEOUT_S)
        except Exception as e:  # noqa: BLE001 — مهلة/فشل الخيط = لا نتائج كشط
            _log.warning("gmaps finalize timed out/failed: %s", e)
            raw = None

    # روابط مخزّنة (C3): إعادة تشغيل تعيد استعمالها بلا كشط جديد.
    if isinstance(raw, dict) and raw.get("_cached") is not None:
        cached = cache_get(iso3, queries) or []
        return {"leads": _merge_web_candidates(cached, web_candidates),
                "path": "cache", "note": "روابط من التخزين المؤقت (لكل سوق/استعلام)"}

    leads = parse_and_rank(raw)
    path = "scraper" if leads else ""
    if leads:
        cache_put(iso3, queries, leads)
    else:
        # الجامع بلغ مهلته القصيرة؟ ربما خزّن الخيطُ متأخراً — جرّب المخزن.
        late = cache_get(iso3, queries)
        if late:
            leads, path = late, "cache"
    if not leads:  # C4: المكشطة سقطت/فارغة ⇒ Places الرسمي
        leads = places_fallback(product, market_ref)
        path = "places" if leads else "gap"

    merged = _merge_web_candidates(leads, web_candidates)
    note = {
        "scraper": "مرصود عبر مكشطة خرائط قوقل (هاتف/إيميل)",
        "places": "المكشطة غير متاحة — احتياط Places الرسمي (بلا إيميل)",
        "gap": "تعذّر رصد جهات اتصال قابلة للتواصل — فجوة معلنة",
    }.get(path, "")
    if not merged and web_candidates:
        # لا رواد خرائط لكن مرشّحو ويب موجودون — أسماء فقط، معلَنة.
        merged = _merge_web_candidates([], web_candidates)
        path = path or "gap"
    return {"leads": merged, "path": path or "gap", "note": note}
