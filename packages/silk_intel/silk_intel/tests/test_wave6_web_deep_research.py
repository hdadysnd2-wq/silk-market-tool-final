"""اختبارات الموجة ٤د (V5): لوحة البحث العميق في web/index.html.

يغطي: القالب الموحّد نفسه (لا مسار عرض موازٍ — renderBoard يتفرّع لا
يُستبدَل)، وجود دالة renderDeepResearch مربوطة بـ v.deep_research، وأن
جافاسكربت الملف صحيح النحو بعد التعديل (فحص node --check حين متاح).
Run:  python3 -m pytest tests/ -q
"""
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_HTML = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "web", "index.html")


def _html() -> str:
    return open(_HTML, encoding="utf-8").read()


def test_deep_research_render_function_wired_into_render_board():
    html = _html()
    assert "function renderDeepResearch(" in html
    assert "if(v.deep_research){renderDeepResearch(v);return}" in html
    # نفس القالب الموحّد — لا استيراد لمسار عرض جديد، الدالة تقرأ v فقط.
    assert "v.deep_research" in html


def test_deep_research_panel_uses_the_five_intersections():
    html = _html()
    for cat in ("demand", "entry_cost", "price_competitiveness",
               "entry_door", "swot"):
        assert f'{cat}:"' in html or f"{cat}:" in html


def test_category_grid_uses_confidence_badge_not_raw_number():
    """P2 (مراجعة أرقام منفصلة بلا معنى): شبكة التقاطعات الخمس كانت تطبع
    ثقة عشرية خامة (· ثقة 0.6) — يجب أن تعرض شارة الأدلة الجاهزة من
    نموذج العرض (confidence_badge) بدل تصنيف خام في JS العميل."""
    html = _html()
    assert "f.confidence_badge" in html
    assert "· ثقة '+f.confidence" not in html
    assert "'+f.confidence+'" not in html


def test_full_report_promoted_above_raw_evidence_in_dom():
    """التقرير الكامل المكتوب يظهر قبل قسم "الأدلة الخام" (البعثات
    وتقاطعات المحلل) في ترتيب DOM — كان مدفوناً تحته في صندوق تمرير ضيّق."""
    html = _html()
    fn_start = html.index("function renderDeepResearch(")
    fn_end = html.index("function renderBoard(")
    body = html[fn_start:fn_end]
    report_idx = body.index("التقرير الكامل (كاتب مراجَع")
    raw_evidence_idx = body.index("الأدلة الخام")
    assert report_idx < raw_evidence_idx
    # جدول البعثات وشبكة التقاطعات صارا داخل <details> ثانوي مطويّ افتراضياً.
    details_idx = body.index("<details")
    missions_table_idx = body.index("البعثة</th>")
    assert details_idx < missions_table_idx
    assert "max-height:420px" not in body


def test_javascript_syntax_is_valid_after_edit():
    node = shutil.which("node")
    if not node:
        return  # بيئة بلا node — لا يُفشَل الاختبار، فحص أفضل الجهد
    import re
    import tempfile
    m = re.search(r"<script>(.*)</script>", _html(), re.S)
    assert m, "no <script> block found"
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as f:
        f.write(m.group(1))
        tmp_path = f.name
    try:
        proc = subprocess.run([node, "--check", tmp_path],
                              capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
    finally:
        os.unlink(tmp_path)
