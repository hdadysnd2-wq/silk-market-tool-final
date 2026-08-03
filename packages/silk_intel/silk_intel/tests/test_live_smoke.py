"""طبقة دخان حية (opt-in) — real-network integration smoke test.

**تُتخطّى في CI الافتراضي.** تعمل فقط حين `SILK_RUN_LIVE=1` (مسار يدوي،
`.github/workflows/live-smoke.yml`). الغرض: إغلاق أكبر فجوة اختبار في
المستودع — لا يوجد أي اختبار تكامل حي؛ كل شيء آخر يقطع الشبكة. هذه الطبقة
تثبت أن مسار الشبكة الحقيقي ما زال يعمل (تغيّر مخطّط/نقطة نهاية المصدر
يُكشَف هنا) دون أي مفتاح مدفوع ولا حرق أرصدة كلود/كومتريد.

المصدر المستعمل: **البنك الدولي فقط** — مجاني، بلا مفتاح، الأكثر استقراراً
(silk_data_layer.world_bank). لا كلود، لا كومتريد المدفوع، لا Serper.

Run locally:  SILK_RUN_LIVE=1 python3 -m pytest tests/test_live_smoke.py -q
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.live


def test_world_bank_live_returns_a_real_value():
    """مؤشر مستقر (سكان الولايات المتحدة، SP.POP.TOTL) يجب أن يعود برقم
    حقيقي موجب من البنك الدولي — إن تغيّرت واجهة/مخطّط WB فسيُكشَف هنا."""
    from silk_data_layer import world_bank
    dp = world_bank("USA", "SP.POP.TOTL")
    # عقد DataPoint سليم دائماً، حتى لو تعذّر الجلب لحظياً.
    assert dp.value is None or isinstance(dp.value, (int, float))
    assert dp.source and dp.retrieved_at
    # التأكيد الجوهري: المسار الحي أعاد رقماً حقيقياً (لا فجوة).
    assert dp.value is not None, (
        f"World Bank live path returned no value — {dp.note!r}. "
        "لو تكرّر: تحقّق من تغيّر واجهة/مخطّط البنك الدولي.")
    assert dp.value > 0
    assert 0.0 < dp.confidence <= 1.0


def test_world_bank_live_honors_no_fabrication_on_a_bad_indicator():
    """المبدأ المؤسِّس حياً: مؤشر غير موجود يُعلَن فجوة (value=None،
    confidence=0.0) لا يُختلَق رقماً — يثبت أن العقد يصمد على الشبكة الحقيقية
    لا في الاختبارات المقطوعة فقط."""
    from silk_data_layer import world_bank
    dp = world_bank("USA", "THIS.INDICATOR.DOES.NOT.EXIST")
    assert dp.value is None
    assert dp.confidence == 0.0
    assert dp.note  # سبب الفجوة معلَن
