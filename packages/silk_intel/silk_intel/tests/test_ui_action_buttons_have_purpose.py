"""LESSONS.md البند ٩ (حارس عام، لا ثلاثة أزرار مثبَّتة): لا زرّ فعل يُشحَن
بلا غرض مُصرَّح؛ وكل زرّ في شريط الفعل الرئيسي (منطقة `runbar` — مشغّلات
التكلفة/التحليل) يحمل تلميحاً (title) يشرح ماذا يفعل وبأي تكلفة.

test_item3_analyze_screen_button.py يقفل الأزرار الثلاثة المعروفة بالاسم؛
هذا يعمّم القاعدة: زرّ فعل **جديد** يُضاف لشريط الفعل بلا تلميح يُفشِل
الاختبار فوراً بدل أن يتسرّب زرٌّ لا يستطيع المالك شرح غرضه (بالضبط عائلة
البلاغ: «لقطة سريعة/حلّل السوق» أزرار غامضة تآكلت بها الثقة).

Run: python3 -m pytest tests/test_ui_action_buttons_have_purpose.py -q
"""
import os
import re

_HTML = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "web", "index.html")


def _html() -> str:
    return open(_HTML, encoding="utf-8").read()


def _static_buttons(html: str):
    """(كامل الوسم، النص الداخلي) لكل <button> ساكن في المُعلّم — نتخطّى
    الأزرار المولَّدة داخل سلاسل JS (تحمل '+ في وسمها) لأنها ليست عناصر
    ساكنة قابلة للتفتيش نصياً بثقة."""
    out = []
    for m in re.finditer(r"<button\b([^>]*)>(.*?)</button>", html, re.S):
        attrs, inner = m.group(1), m.group(2)
        if "'+" in attrs or '"+' in attrs:   # جزء قالب JS لا عنصر ساكن
            continue
        out.append((attrs, inner))
    return out


def test_every_static_button_has_a_stated_purpose():
    """كل زرّ ساكن يحمل غرضاً مقروءاً: تلميح (title) أو مفتاح تسمية (data-t)
    أو نصّ/أيقونة مرئية داخله — لا زرّ لغز فارغ بلا أي إشارة."""
    bare = []
    for attrs, inner in _static_buttons(_html()):
        has_title = "title=" in attrs
        has_label_key = "data-t=" in attrs
        # نصّ داخلي مرئي بعد نزع أي وسوم داخلية (<span data-t=..> يحمل تسميته)
        visible_text = re.sub(r"<[^>]+>", "", inner).strip()
        has_inner_label_key = "data-t=" in inner
        if not (has_title or has_label_key or visible_text or has_inner_label_key):
            bare.append(attrs.strip()[:80])
    assert not bare, f"أزرار بلا غرض مُصرَّح (لا title/label/نص): {bare}"


def test_every_runbar_action_button_has_a_tooltip():
    """كل زرّ في شريط الفعل الرئيسي (runbar) — مشغّلات التكلفة/التحليل — يحمل
    title غير فارغ. زرّ فعل جديد بلا تلميح يُفشِل هذا فوراً (تعميم القاعدة
    خارج الأزرار الثلاثة المثبَّتة بالاسم في test_item3)."""
    html = _html()
    # نلتقط من فتح runbar حتى إغلاق آخر زرّ (`</button></div>`) — مرساة ثابتة
    # لا تعتمد على عنصر بعده (snapOut حُذف مع «معاينة فورية»، PART D).
    m = re.search(r'<div class="runbar">(.*?</button>\s*</div>)', html, re.S)
    assert m, "لم يُعثر على شريط الفعل runbar — هل تغيّرت البنية؟"
    runbar = m.group(1)
    buttons = re.findall(r"<button\b([^>]*)>", runbar)
    assert len(buttons) >= 2, f"عدد أزرار runbar غير متوقَّع: {len(buttons)}"
    missing = []
    for attrs in buttons:
        mt = re.search(r'title="([^"]*)"', attrs)
        if not (mt and mt.group(1).strip()):
            bid = re.search(r'id="([^"]+)"', attrs)
            missing.append(bid.group(1) if bid else attrs.strip()[:60])
    assert not missing, (
        f"أزرار في شريط الفعل بلا تلميح title يشرح الغرض/التكلفة: {missing}")


def test_runbar_holds_the_two_final_actions_no_snapshot():
    """حارس انحدار: الواجهة النهائية (PART D) فعلان فقط — بحث عميق + مسح
    الأسواق؛ «معاينة فورية» (snapBtn) محذوف بالكامل، لا يتيم متبقٍّ."""
    html = _html()
    m = re.search(r'<div class="runbar">(.*?</button>\s*</div>)', html, re.S)
    runbar = m.group(1)
    for bid in ("researchBtn", "runBtn"):
        assert f'id="{bid}"' in runbar, f"زرّ {bid} غاب عن شريط الفعل"
    assert 'id="snapBtn"' not in html   # الزرّ محذوف من كل الملف
