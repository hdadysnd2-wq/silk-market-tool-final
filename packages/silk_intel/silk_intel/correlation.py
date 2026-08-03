"""محرّك التقاطع لسِلك — Silk Correlation Engine (wave 4, vision §1).

الطبقة الجديدة الوحيدة: تربط نتائج الوكلاء الموجودة في الذاكرة حول **منتج
المستخدم** (بطاقة المنتج) لتنتج خيوطاً مترابطة — من "تقرير عن السوق" إلى
"خطة دخولك أنت للسوق".

**القاعدة الصارمة (vision §3):** هذه الوحدة لا تستدعي أي API خارجي ولا
كلود — تعمل حصراً على نتائج الوكلاء الممرَّرة إليها في الذاكرة. صفر تكلفة
إضافية، صفر سطح حقن جديد. لا `import requests` هنا إطلاقاً (اختبار بنيوي
يثبته)، وأي ربط يحتاج بيانات غير موجودة **يُعلن فجوةً** ("خيط غير مكتمل")
— نفس مبدأ "لا اختلاق".

الخيوط (vision §4):
  1. competitor_threads — منافس مُسمّى ← سعره المرصود ← قنواته ← مورّدوه.
  2. feasibility_threads — هامش المستخدم ضد كل منافس له سعر مرصود
     (تكلفة + جمارك مرصودة + شحن معلَن كافتراض قابل للتعديل).
  3. entry_thread — أبواب الدخول المرصودة بتقييم صادق (لا هيمنة مخترعة).
  4. contacts_thread — جهات explee إن فُعّل التعميق، وإلا فجوة معلنة.

المطابقة نصية بسيطة بعتبة متحفظة (vision §8) — والغامض يُعلن غامضاً.
"""
from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)

# عتبة المطابقة المتحفظة — conservative Dice threshold over distinctive
# tokens (vision §8): نصف الرموز المميِّزة مشتركاً على الأقل.
_MATCH_THRESHOLD = 0.5

# كلمات عامة تُستبعد من المطابقة — generic tokens excluded from name matching
# (وإلا طابق اسمُ المنتج كلَّ قائمة بكل منافس).
_GENERIC = {"best", "top", "brands", "brand", "companies", "company", "list",
            "premium", "quality", "price", "prices", "buy", "online", "shop",
            "kg", "the", "and", "for", "with", "من", "في", "أفضل", "شركة",
            "شركات", "علامات", "قائمة", "سعر", "أسعار"}


def _value(finding: object) -> object:
    """قيمة النتيجة — .value whether DataPoint or plain dict."""
    if isinstance(finding, dict):
        return finding.get("value")
    return getattr(finding, "value", None)


def _tokens(text: str, stop: set[str]) -> set[str]:
    """رموز مميِّزة للمطابقة — distinctive tokens (len>=4, non-generic)."""
    words = re.findall(r"[\w؀-ۿ]+", (text or "").lower())
    return {w for w in words if len(w) >= 4 and w not in stop and w not in _GENERIC}


def _match_listing(comp_title: str, listings: list[dict],
                   stop: set[str]) -> tuple[dict | None, float]:
    """طابق منافساً بقائمة مسعّرة — best conservative listing match, or None.

    المقياس: معامل Dice على **الرموز المميِّزة** (بعد استبعاد كلمات المنتج
    والعموميات) — تقاطع رمز علامة تجارية كـ"Foah" هو الإشارة المقصودة، بينما
    نسبة difflib على العناوين الكاملة تنخدع بذيول العناوين المختلفة.
    ما دون العتبة: "سعر غير مرصود" (الغامض يُعلن غامضاً، لا يُخمَّن).
    """
    ctoks = _tokens(comp_title, stop)
    if not ctoks:
        return None, 0.0
    best, best_score = None, 0.0
    for it in listings:
        ltoks = _tokens(str(it.get("title") or ""), stop)
        shared = ctoks & ltoks
        if not shared:
            continue  # لا رمز مشترك مميِّز => لا مطابقة
        dice = 2 * len(shared) / (len(ctoks) + len(ltoks))
        if dice > best_score:
            best, best_score = it, dice
    if best is not None and best_score >= _MATCH_THRESHOLD:
        return best, round(best_score, 2)
    return None, 0.0


def _listings(row: dict) -> list[dict]:
    """القوائم المسعّرة المرصودة — priced listings from the localprice layer."""
    out = []
    for f in row.get("localprice") or []:
        v = _value(f)
        if isinstance(v, dict) and v.get("price") is not None:
            out.append(v)
    return out


def _channel_candidates(row: dict) -> list[dict]:
    """قنوات مرصودة — observed channel candidates from the channels layer."""
    out = []
    for f in row.get("channels") or []:
        v = _value(f)
        if isinstance(v, dict) and v.get("title"):
            out.append(v)
    return out


def _supplier_names(row: dict) -> list[str]:
    """مورّدون/مستوردون بالاسم — names from volza (documented) + maps."""
    names: list[str] = []
    for f in row.get("volza") or []:
        v = _value(f)
        if isinstance(v, str) and v.strip():
            names.append(v.strip())
    for f in row.get("maps") or []:
        v = _value(f)
        if isinstance(v, dict) and v.get("name"):
            names.append(str(v["name"]))
    return names


def _contacts(row: dict) -> list[str]:
    """جهات اتصال explee — contact strings when /deepen ran, else []."""
    out = []
    for f in row.get("explee") or []:
        v = _value(f)
        if isinstance(v, str) and v.strip():
            note = (f.get("note") if isinstance(f, dict)
                    else getattr(f, "note", "")) or ""
            out.append(f"{v.strip()} — {note}" if note else v.strip())
    return out


def _tariff_pct(row: dict) -> float | None:
    """الرسوم المرصودة — the observed applied tariff %, or None (declared gap)."""
    dp = row.get("tariff")
    v = _value(dp) if dp is not None else None
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _margin_pct(price: float, landed: float) -> float:
    """هامش % من سعر البيع — margin as % of the selling price."""
    return round(100.0 * (price - landed) / price, 1) if price else 0.0


def correlate(row: dict, product_card: dict, product_name: str = "") -> dict:
    """اربط خيوط سوق واحد — correlate one market row around the user's product.

    يعمل حصراً على ما في `row` من نتائج وكلاء (ذاكرة) + بطاقة المنتج.
    كل خيط ناقص يُعلن نقصه حرفياً — لا سعر يُخترع ولا منافس يُسقط بصمت.
    """
    stop = _tokens("", set()) | {w.lower() for w in
                                 re.findall(r"[\w؀-ۿ]+", product_name)}
    listings = _listings(row)
    channels = _channel_candidates(row)
    suppliers = _supplier_names(row)
    contacts = _contacts(row)
    tariff_pct = _tariff_pct(row)

    cost = float(product_card.get("cost_per_unit") or 0.0)
    shipping = float(product_card.get("shipping_per_unit") or 0.0)
    # سدّ تسريب: كانت الملاحظة تُرشد القارئ لتمرير اسم معامل بايثون خام
    # (shipping_per_unit) — عميل تجاري لا يستدعي دالة؛ التحديث الفعلي يمرّ
    # عبر بطاقة المنتج (product_card) في الطلب، فالصياغة تعكس ذلك.
    shipping_note = ("افتراض شحن معلَن قابل للتعديل: "
                     f"{shipping} لكل وحدة — حدِّثه في بطاقة المنتج "
                     "لحساب أدق للهامش")

    # خيط ١ — ملفات المنافسين المترابطة.
    competitor_threads: list[dict] = []
    for f in row.get("competitors_named") or []:
        v = _value(f)
        if not isinstance(v, dict) or not v.get("title"):
            continue
        name = str(v["title"])
        listing, ratio = _match_listing(name, listings, stop)
        thread = {
            "name": name,
            "source_link": v.get("link"),
            "observed_price": None,
            "price_flag": "سعر غير مرصود",
            "channels": [c.get("title") for c in channels][:5],
            "suppliers": suppliers[:5],
            "contacts_available": bool(contacts),
        }
        if listing is not None:
            thread["observed_price"] = {
                "value": listing.get("price"),
                "currency": listing.get("currency"),
                "store": listing.get("store"),
                "matched_listing": listing.get("title"),
                "match_ratio": ratio,
            }
            thread["price_flag"] = "سعر مرصود من قائمة فعلية"
        slots = [thread["observed_price"] is not None, bool(channels),
                 bool(suppliers), bool(contacts)]
        thread["thread_completeness"] = f"{sum(slots)}/4"
        competitor_threads.append(thread)

    # خيط ٢ — الجدوى ضد كل منافس له سعر مرصود.
    feasibility_threads: list[dict] = []
    for t in competitor_threads:
        obs = t["observed_price"]
        if not obs or obs.get("value") is None:
            continue
        try:
            price = float(obs["value"])
        except (TypeError, ValueError):
            continue
        gaps = [shipping_note]
        if tariff_pct is None:
            landed = cost + shipping
            gaps.append("الرسوم الجمركية غير مرصودة — الهامش أدناه محسوب "
                        "بلا احتساب جمارك")
        else:
            landed = (cost + shipping) * (1 + tariff_pct / 100.0)
        if obs.get("currency"):
            gaps.append(f"عملة القائمة كما وردت ({obs['currency']}) — "
                        "وحّد العملة مع تكلفتك قبل الاعتماد")
        feasibility_threads.append({
            "competitor": t["name"],
            "observed_price": price,
            "currency": obs.get("currency"),
            "landed_cost": round(landed, 2),
            "cost_per_unit": cost,
            "shipping_per_unit": shipping,
            "tariff_pct": tariff_pct,
            "margin_at_match_pct": _margin_pct(price, landed),
            "margin_at_10pct_below": _margin_pct(price * 0.9, landed),
            "assumptions_and_gaps": gaps,
        })

    # خيط ٣ — أبواب الدخول (تقييم صادق: لا هيمنة مخترعة).
    doors = []
    for c in channels:
        kind = c.get("channel_type") or "unknown"
        assessment = ("واقعية — قناة إلكترونية مفتوحة" if kind == "digital"
                      else "تتطلب تحققاً ميدانياً — هيمنة الموردين غير مرصودة")
        doors.append({"name": c.get("title"), "type": kind,
                      "assessment": assessment, "link": c.get("link")})
    entry_thread = {
        "doors": doors,
        "importers": suppliers if suppliers
        else ["فعّل التعميق (Volza) للحصول على الأسماء الموثّقة"],
        "note": ("لا قنوات توزيع مرصودة — فعّل طبقة قنوات التوزيع لرصدها"
                 if not doors else
                 "ترتيب أوّلي من مرشحات مرصودة — تحقق قبل التعاقد"),
    }

    # خيط ٤ — جهات الاتصال (deepen/explee أو فجوة معلنة).
    contacts_thread = {
        "contacts": contacts if contacts
        else [],
        "note": ("جهات موثّقة من explee — استخدام تواصل تجاري مشروع فقط"
                 if contacts else
                 "فعّل التعميق (explee) لجهات الاتصال — لا جهات مرصودة"),
    }

    observed = sum(1 for t in competitor_threads if t["observed_price"])
    return {
        "product_card": {k: product_card.get(k) for k in
                         ("cost_per_unit", "unit", "tier", "monthly_capacity",
                          "shipping_per_unit")},
        "competitor_threads": competitor_threads,
        "feasibility_threads": feasibility_threads,
        "entry_thread": entry_thread,
        "contacts_thread": contacts_thread,
        "coverage": (f"{observed} من {len(competitor_threads)} منافساً لهم "
                     "أسعار مرصودة — لرفع التغطية فعّل طبقة التعميق"
                     if competitor_threads else
                     "لا مرشحي منافسين مرصودين — فعّل طبقتي المنافسين "
                     "والأسعار لرصدهم"),
        "note": ("خيوط مربوطة من نتائج الوكلاء في الذاكرة حصراً — صفر "
                 "استدعاءات خارجية؛ كل نقص معلن لا مُخمّن."),
    }
