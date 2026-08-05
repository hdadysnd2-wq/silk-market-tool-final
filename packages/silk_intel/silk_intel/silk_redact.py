"""تنقيح الأسرار من روابط رسائل الفشل — Silk secret-redaction helper (C3).

مفاتيح المزوّدين المدفوعة/المجانية تُمرَّر أحياناً في **سلسلة استعلام** الرابط
(المزوّد يفرضها ولا يقبل ترويسة — SerpApi `api_key=`، Google Maps `key=`)؛ ورسالة
استثناء requests تُضمِّن الرابط كاملاً («... for url: ...?...&api_key=<SECRET>»).
تُكتب هذه الرسالة في السجلّ **وقد تظهر في ملاحظة تصل تقرير العميل** (وكيل الخرائط
مجّاني، مساره يغذّي التقرير المجاني) — فتسريب المفتاح خطر حقيقي.

`redact_url` تبتر سلسلة الاستعلام من أي رابط في النص (تنقيح **مستقلّ عن قيمة
المفتاح واسم المعامل** — لا شيء في الاستعلام يمكن أن يتسرّب مهما كان الترميز)، مع
حجبٍ إضافيٍّ لقيمة سرّ معلوم إن مُرِّرت وكانت بطول مفتاحٍ حقيقي (حارس الحدّ الأدنى
يتجنّب تشويه نصٍّ مشروع قصير — الدرس L2). Strips the query string from any URL in
the text — value- and param-name-independent — plus an optional literal mask of a
known secret guarded by a minimum length (L2: never mangle short legitimate text).

بلا شبكة ولا مفاتيح؛ مكتبة قياسية فقط (`re`) فيستورد المتصفَّح دون أثر جانبي.
"""
from __future__ import annotations

import re

# رابط + سلسلة استعلامه — the query string is where key params ride.
_URL_QUERY_RE = re.compile(r"(https?://[^\s?'\"]+)\?[^\s'\"]*")

# أقصر مفتاح مزوّد حقيقي معقول — real provider keys are long; below this a literal
# replace risks mangling ordinary text (product/source names), so we skip it (L2).
_MIN_SECRET_LEN = 8


def redact_url(text: str, *, secret: str | None = None) -> str:
    """انزع أسرار الاستعلام من نصّ فشلٍ قبل تسجيله/عرضه — mask query-string secrets.

    - يبتر سلسلة استعلام كل رابط `https?://…?…` إلى `…?<redacted>` (لا يعتمد على
      قيمة المفتاح ولا على اسم المعامل، فلا يفلت مفتاح حتى لو رُمِّز الرابط).
    - إن مُرِّر `secret` بطول ≥ ٨، يحجب أي ظهور حرفيّ له أيضاً (احتياط لمفتاح قد
      يظهر خارج استعلام رابط) — دون تشويه نصٍّ قصير مشروع.
    """
    out = str(text or "")
    out = _URL_QUERY_RE.sub(r"\1?<redacted>", out)
    if secret and len(secret) >= _MIN_SECRET_LEN:
        out = out.replace(secret, "***")
    return out
