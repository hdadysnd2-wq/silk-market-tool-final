"""عيّنة ملتزَمة (§10.6) — التقرير الكامل لحالة البطارية المرجعية الأصلية
(Master Prompt Part 2 §F، البند ١٣): زبدة الفول السوداني × الكويت.

يبني من `tools/canonical_kuwait_peanut_butter.kuwait_research_blob()` نفسه
(المدوّنة القانونية التي تُختبَر عليها بوّابات §A-§D في `tests/
test_golden_deep_research_contract.py` و`tests/test_benchmark_battery_part2.py`)
عبر مسار العرض الحقيقي (`build_view` → `run_quality_gate` → `render_docx`)
— نفس ما يراه المشغّل لتشغيلةٍ حقيقية، لا نموذجاً مبسّطاً منفصلاً.

Run: python3 tools/gen_kuwait_battery_sample.py
"""
from __future__ import annotations

import os
import sys

os.environ["SILK_HERMETIC"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from silk_render import build_view  # noqa: E402
from silk_reports import render_docx, render_markdown  # noqa: E402
import silk_quality_gate  # noqa: E402
from tools.canonical_kuwait_peanut_butter import kuwait_research_blob  # noqa: E402

view = build_view(kuwait_research_blob())

# بوابة الجودة تعمل هنا أيضاً كما في /research الفعلي — نتيجتها الحقيقية
# («هل تُفشِل بوّابة إعادة تأطير الرمز/تناقض السعر الحكم؟») تظهر في العيّنة.
gate_out = silk_quality_gate.run_quality_gate(view)
view["deep_research"]["quality_gate"] = gate_out

_repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
docx_path = os.path.join(_repo_root, "samples",
                        "kuwait_peanut_butter_research_report.docx")
render_docx(view, docx_path)
print("wrote", docx_path, "— quality gate:", gate_out["verdict"])

md_path = os.path.join(_repo_root, "samples",
                       "kuwait_peanut_butter_research_report.md")
with open(md_path, "w", encoding="utf-8") as fh:
    fh.write(render_markdown(view))
print("wrote", md_path)
