"""LESSONS.md البند ١١ (قفل test-first، البلاغ الحي الثالث لعائلة 501 تصدير
العميل): «فشل التنزيل: HTTP 501» تكرّر بعد فكسَي #90 و#103 — كل مرة كان العلاج
مطاردة المصطلح المتسرِّب الواحد بعد وقوعه. السبب الجذري البنيوي: حارس تصدير
العميل (`_client_forbidden_hits`) يملك محفّزات عربية **لا يقابلها أي استبدال**
في المُطهِّر (`_CLIENT_SANITIZE`) — فأي نثر كاتب جديد يلمس واحداً منها يُسقِط
التصدير كله بـ501 بدل أن يُحوَّل لمفردة تجارية آمنة.

القفل الميكانيكي هنا: **تغطية المُطهِّر يجب أن تشمل كل محفّز عربي في الحارس**
— تُستخرَج المحفّزات آلياً من أنماط الحارس نفسها، فإضافة نمط حارس جديد بلا
استبدال مقابل تُفشِل هذا الاختبار فوراً (لا انتظار البلاغ الحي الرابع).

اكتُشف بإعادة إنتاج محلية مباشرة (2026-07-16): «استدعاء أداة» و«بوابة الجودة»
و«بلا استشهاد» كانت كلها تمرّ من المُطهِّر ثم يرفضها الحارس.

Run: python3 -m pytest tests/test_client_sanitizer_covers_guard.py -q
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _arabic_literals(pattern_str: str) -> set[str]:
    """استخرج البدائل الحرفية العربية من نص نمط حارس — البدائل الحاوية رموز
    regex معقّدة أو حدود كلمات إنجليزية تُغطّى يدوياً في _HAND_VARIANTS."""
    outs: set[str] = set()
    for alt in re.split(r"\|", pattern_str):
        alt = alt.strip()
        if not alt or "\\b" in alt:
            continue
        variants = [alt]
        while any("(?:ال)?" in v for v in variants):
            nxt = []
            for v in variants:
                if "(?:ال)?" in v:
                    nxt.append(v.replace("(?:ال)?", "ال", 1))
                    nxt.append(v.replace("(?:ال)?", "", 1))
                else:
                    nxt.append(v)
            variants = nxt
        for v in variants:
            v = v.replace(r"\s+", " ")
            if re.search(r"[\\\[\]\(\)\?\*\+\{\}]", v):
                continue
            outs.add(v)
    return outs


# صيغ الأنماط المعقّدة (كمّيات/حدود كلمات) التي يتخطّاها الاستخراج الآلي —
# مكتوبة يدوياً كسلاسل مطابِقة فعلياً لأنماط الحارس، وتشمل صيغ dpN/datapoint
# التي قد يكتبها الكاتب في نثره عند الاستشهاد.
_HAND_VARIANTS = [
    "نداء أدوات", "نداءات أدوات",        # call: نداء(?:ات)?\s+أدوات?
    "استدعاء أداة",                      # call: استدعاء\s+أداة
    "مبنية على استشهاد", "مبنيّة على استشهاد",  # citation_plumbing
    "بلا استشهاد",                        # citation_plumbing
    "dp7", "(dp3)", "datapoint",          # citation_plumbing: \bdp\d+\b|\bdatapoint\b
]


def test_every_arabic_guard_trigger_is_neutralized_by_the_sanitizer():
    """التغطية الآلية: كل بديل عربي حرفي في كل نمط حارس يخرج نظيفاً من
    المُطهِّر — نمط حارس جديد بلا استبدال مقابل = فشل فوري هنا."""
    import silk_reports as R

    uncovered = []
    for label, pat in R._CLIENT_FORBIDDEN_PATTERNS:
        for lit in sorted(_arabic_literals(pat.pattern)):
            cleaned = R._client_sanitize(f"نص يحوي {lit} داخل فقرة سردية.")
            hits = R._client_forbidden_hits(cleaned)
            if hits:
                uncovered.append(f"[{label}] «{lit}» → {hits}")
    assert not uncovered, (
        "محفّزات حارس بلا تغطية مُطهِّر — هذا بالضبط ما أنتج 501 الحي الثالث:\n"
        + "\n".join(uncovered))


def test_hand_listed_complex_variants_are_neutralized_too():
    """الصيغ المعقّدة (كمّيات/dpN) المُغطّاة يدوياً — نفس العقد."""
    import silk_reports as R

    uncovered = []
    for lit in _HAND_VARIANTS:
        cleaned = R._client_sanitize(f"نص يحوي {lit} داخل فقرة سردية.")
        hits = R._client_forbidden_hits(cleaned)
        if hits:
            uncovered.append(f"«{lit}» → {hits}")
    assert not uncovered, "صيغ معقّدة بلا تغطية:\n" + "\n".join(uncovered)


def test_the_three_live_leak_phrases_render_as_business_vocabulary():
    """الصياغات الثلاث المكتشفة بالبلاغ الحي الثالث تتحوّل لمفردات تجارية
    مفهومة (لا حذف صامت يترك جملة مبتورة)."""
    import silk_reports as R

    out1 = R._client_sanitize("جرى استدعاء أداة للتحقق من السعر.")
    assert "استدعاء أداة" not in out1 and "جمع البيانات" in out1
    out2 = R._client_sanitize("روجِع التقرير عبر بوابة الجودة قبل التسليم.")
    assert "بوابة الجودة" not in out2 and "مراجعة الجودة" in out2
    out3 = R._client_sanitize("وردت ادعاءات بلا استشهاد فاستُبعدت.")
    assert "بلا استشهاد" not in out3 and "دون توثيق مصدر" in out3


def test_dlreport_surfaces_the_501_detail_not_bare_status():
    """الواجهة: dlReport كان يبتلع جسم الـ501 (الذي يسمّي المصطلح المرفوض
    بالضبط) ويعرض «HTTP 501» فقط — نفس عائلة «401 المبتلَع» (بلاغ ٢).
    القفل: مسار التنزيل يقرأ الجسم ويمرّره عبر detailText إلى الرسالة."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    html = open(os.path.join(root, "web", "index.html"), encoding="utf-8").read()
    m = re.search(r"function dlFail\(r\)\{.*?\n\$\(\"#pdfBtn\"\)", html, re.S)
    assert m, "لم يُعثر على كتلة dlFail/dlReport — هل انتقلت؟"
    body = m.group(0)
    # لا رمي عارٍ بالحالة فقط داخل مسار التنزيل — الجسم يُقرأ ويُعرَض.
    assert 'throw new Error("HTTP "+r.status)' not in body, (
        "مسار التنزيل لا يزال يبتلع جسم الخطأ — التفصيل (اسم المصطلح "
        "المرفوض) يجب أن يصل المستخدم")
    assert "detailText" in body, "مسار التنزيل لا يمرّر التفصيل عبر detailText"
    # كلا الفرعين (docx وmd) يمرّان عبر القارئ الموحّد للجسم.
    assert body.count("dlFail(r)") >= 2, "فرع md لا يمرّ عبر dlFail"
