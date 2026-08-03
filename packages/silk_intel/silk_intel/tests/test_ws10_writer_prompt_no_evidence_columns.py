"""WS10 المرحلة ٢ — برومبت الكاتب لم يعد يوجّه أعمدة مصدر/توثيق أو شارة ○.

قفلٌ هرمتيّ بفحص مصدر `silk_ai_judge.deep_report`: بعد إزالة تعليمات عمود
«المصدر» (جدول الطلب) و«مستوى التوثيق» (جدول التسعير) وشارة ○ لمرشّحي باب
الدخول — لا يجوز أن تعود أيٌّ منها إلى البرومبت (وإلا يعيد الكاتب توليد أعمدة
الإسناد في متن التقرير الذي قرّر المالك تنظيفه). لا يستدعي هذا الاختبار أيّ
نموذج (فحص نصّ المصدر فقط، صفر تكلفة).

Run:  python3 -m pytest tests/test_ws10_writer_prompt_no_evidence_columns.py -q
"""
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _writer_prompt_source() -> str:
    import silk_ai_judge as J
    return inspect.getsource(J.deep_report)


def test_demand_table_instruction_has_no_source_column():
    src = _writer_prompt_source()
    # الترويسة القديمة ثلاثية بعمود «المصدر» ممنوعة؛ الجديدة عمودان.
    assert "المتغيّر | القيمة | المصدر" not in src
    assert "| المتغيّر | القيمة" in src   # الترويسة النظيفة باقية


def test_pricing_table_instruction_has_no_doc_level_column():
    src = _writer_prompt_source()
    # عمود «مستوى التوثيق» أُزيل من جدول التسعير (وأينما ورد في البرومبت).
    assert "مستوى التوثيق" not in src
    assert "ومستوى توثيقه" not in src      # تعليمة الصفّ المرافقة أُزيلت أيضاً
    assert "المتجر وتاريخ الرصد |" in src  # نهاية الترويسة النظيفة باقية


def test_entry_door_candidates_have_no_circle_marker():
    src = _writer_prompt_source()
    # شارة ○ لمرشّحي باب الدخول أُزيلت — لا رمز قوة دليل في متن العميل.
    assert "موسومين ○" not in src
