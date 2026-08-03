"""Wave 3 §2 — سرّية جهة الكتابة (writer-side confidentiality).

أمر العمل الرئيس §2: الكاتب نفسه يجب ألّا يُصدِر تسريباً معمارياً. كانت الحواجز
دفاعيةً فقط (بوابة الجودة + مُنقّي العرض/تقرير العميل) بلا توجيهٍ في موجّه الكاتب،
والموجّهات كانت **تغذّي** النموذج الثنائيةَ المحظورة «بين الحقائق». هذان اختباران
يقفلان: (١) وجود توجيه السرّية في موجّه الكاتب؛ (٢) غياب الثنائية المحظورة من
الموجّهات (نُزِع التحفيز في المصدر). هرمتيّ — تفتيش نصّ المصدر فقط.
"""
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import silk_ai_judge  # noqa: E402
import silk_market_analyst  # noqa: E402


def test_writer_prompt_carries_confidentiality_directive():
    """موجّه الكاتب (deep_report) يحمل توجيه السرّية المعمارية §2 صراحةً —
    يمنع كشف كيفية الإنتاج ويسمّي البنى الممنوعة كي يمتنع عنها النموذج."""
    src = inspect.getsource(silk_ai_judge.deep_report)
    assert "سرّية معمارية" in src
    assert "لا تكشف" in src
    assert "المصادر المتاحة" in src          # الصياغة الآمنة البديلة
    # يسمّي أمثلة البنى الممنوعة صراحةً (نفي موجَّه) كي يمتنع النموذج عنها:
    assert "مسار بحث" in src and "Claude" in src


def test_prompts_do_not_prime_the_banned_facts_bigram():
    """الحارس: لا يُغذّى النموذج الثنائيةَ المحظورة «بين الحقائق» في أيّ موجّه
    (الكاتب/المراجع/المحلّل) — نُزِعت في المصدر لصالح «ضمن الحقائق»، فلا تحفيز
    على ترديد عبارةٍ تُسقِطها بوابة الجودة (facts_list_leak)."""
    for mod in (silk_ai_judge, silk_market_analyst):
        assert "بين الحقائق" not in inspect.getsource(mod), mod.__name__
