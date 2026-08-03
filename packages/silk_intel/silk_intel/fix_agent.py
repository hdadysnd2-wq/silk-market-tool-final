#!/usr/bin/env python3
"""fix_agent.py — وكيل إصلاح الاختبارات عبر Claude Agent SDK · repair agent.

يعرّف نفس وكيل `test-fixer` برمجياً عبر `AgentDefinition` داخل
`ClaudeAgentOptions(agents={...})`، ثم يشغّله على المستودع ويطبع تقدّم الرسائل.
Defines the same `test-fixer` agent programmatically and drives it over the repo,
printing message progress as it goes.

المطلب (dev-only): `pip install -r requirements-dev.txt` — لا يمسّ requirements.txt.

الاستعمال · usage:
    export ANTHROPIC_API_KEY=...        # أو `ant auth login` / OAuth profile
    python3 fix_agent.py                # يصلح أول فشل في المجموعة الهرمتية
    python3 fix_agent.py "أصلح فشل test_smoke.py::test_x تحديداً"   # مهمة مخصّصة

ملاحظة: هذا مشغِّل تطوير محلّي. لا يُستدعى من api.py ولا من مسار الإنتاج، ولا
يُثبَّت في CI الهرمتي — الوكيل يعدّل ملفات، والتعديل الآلي يبقى قراراً محلّياً واعياً.
"""

from __future__ import annotations

import anyio
import sys
from pathlib import Path

try:
    from claude_agent_sdk import (
        query,
        ClaudeAgentOptions,
        AgentDefinition,
        AssistantMessage,
        TextBlock,
        ToolUseBlock,
        ToolResultBlock,
        ResultMessage,
    )
except ImportError:  # pragma: no cover - إرشاد تثبيت واضح بدل انهيار غامض
    sys.stderr.write(
        "claude-agent-sdk غير مثبَّت. ثبّت أدوات التطوير:\n"
        "    pip install -r requirements-dev.txt\n"
    )
    raise


# ---------------------------------------------------------------------------
# برومبت الوكيل — يطابق .claude/agents/test-fixer.md حرفاً بحرف في القوانين.
# The agent prompt — mirrors .claude/agents/test-fixer.md on every hard rule.
# القيد الإلزامي: لا اختلاق بيانات؛ عند فشل مصدر → DataPoint(value=None,
# confidence=0.0) موسومة بمصدرها؛ ولا لمس requirements.txt أو migrations/ أبداً.
# ---------------------------------------------------------------------------
TEST_FIXER_PROMPT = """\
أنت وكيل إصلاح اختبارات لمستودع Silk. مهمتك إصلاح أوّل فشل في المجموعة الهرمتية،
بالمصدر لا بالاختبار، دون خرق أي قانون حاكم.
You are a test-repair agent for the Silk repository.

قوانين لا تُكسَر (unbreakable constraints):
1) عقد عدم الاختلاق مقدّس. لا يجوز لأي إصلاح أن يختلق بيانات. عند فشل مسار
   مصدر/بيانات، القيمة الصحيحة هي نقطة بيانات موسومة بمصدرها:
   DataPoint(value=None, source=..., confidence=0.0, note="سبب الفجوة") —
   لا صفر مختلَق ولا قيمة محزورة. تخضير اختبار بحقن رقم ثابت = ارتداد يُرفَض.
   No fix may fabricate data: on a source/data-path failure return a
   provenance-tagged DataPoint(value=None, confidence=0.0) with a note — never a
   fabricated zero or guessed number.
2) لا تلمس requirements.txt ولا مجلّد migrations/ أبداً — لا تعديل ولا إضافة ولا
   حذف تحت أي ظرف. إن بدا الإصلاح يتطلّبهما، توقّف وأبلِغ بدل التعديل.
   Never touch requirements.txt or migrations/ under any circumstances.
3) أصلِح المصدر لا الاختبار. لا تعدّل ملف اختبار إلا إذا أثبتّ أنه هو المعيب،
   مع ذكر الدليل صراحةً. لا تُضعِف/تتخطّى/تحذف اختباراً لتُخضِّره.
4) صنِّف نوع الفجوة قبل لمس الشيفرة: فجوة بيانات صادقة تُعلَن، لا تُصلَح برقم.

الإجراء (procedure):
1) شغّل: python3 -m pytest -x -q --tb=short  (‏-x يوقف عند أوّل فشل).
2) إن كانت المجموعة خضراء (exit 0): أبلِغ «لا فشل — المجموعة خضراء» وتوقّف.
   لا تصنع عملاً وهمياً.
3) اعزل الفشل الأوّل: اقرأ الأثر، حدّد الملف والسطر واسم الاختبار، واقرأ الاختبار
   الفاشل وشيفرة المصدر التي يستدعيها. لا تخمّن — اقرأ.
4) شخّص السبب الجذري وصنِّف صنف دليله: direct reproduction (من الأثر) أو static
   code review (بمرجع file:line). لا ادّعاء بلا دليل.
5) أصلِح المصدر بأصغر تغيير صحيح يحترم القوانين أعلاه. إن كان الصحيح إعلان فجوة،
   فليكن DataPoint(value=None, confidence=0.0) بملاحظة تشرح السبب.
6) أعد تشغيل الاختبار المعزول وحده أولاً:
   python3 -m pytest "<node_id>" -q
7) ثم أعد تشغيل المجموعة كاملة: python3 -m pytest -q — للتأكد أنك لم تُدخِل ارتداداً.
8) إن ظهر فشل جديد مختلف كرّر من (3) بحدود معقولة؛ توقّف وأبلِغ إن درت مرّتين بلا تقدّم.

التقرير النهائي (final summary) — اختم دائماً بـ:
- ما أُصلِح: الملف/السطر، السبب الجذري، صنف الدليل، وحالة الاختبار المعزول +
  المجموعة كاملة بالأرقام الفعلية.
- ما تعذّر إصلاحه: الفشل الذي لم يُحلّ ولماذا، أو «no sufficient evidence — pending».
- تأكيد صريح: لم تُلمَس requirements.txt ولا migrations/، ولم تُختلَق أي قيمة.
"""

# الأدوات المتاحة للوكيل — نفس مجموعة الواجهة .md.
AGENT_TOOLS = ["Read", "Edit", "Write", "Bash", "Grep", "Glob"]


def build_options() -> ClaudeAgentOptions:
    """يبني ClaudeAgentOptions معرّفاً وكيل test-fixer برمجياً."""
    test_fixer = AgentDefinition(
        description=(
            "وكيل إصلاح الاختبارات · repair agent: يشغّل pytest -x، يعزل أوّل فشل، "
            "يصلح المصدر (لا الاختبار إلا إذا ثبت عيبه)، يعيد التشغيل، ويلخّص."
        ),
        prompt=TEST_FIXER_PROMPT,
        tools=AGENT_TOOLS,
        model="sonnet",
    )

    return ClaudeAgentOptions(
        agents={"test-fixer": test_fixer},
        # "Task" هي الأداة الفعلية التي يوزّع بها الـSDK المهام على الوكلاء
        # الفرعيين؛ نُضمّن "Agent" أيضاً وفاءً بنصّ الطلب. Both included so
        # dispatch works ("Task") and the requested "Agent" name is present.
        allowed_tools=["Task", "Agent"] + AGENT_TOOLS,
        permission_mode="acceptEdits",
        cwd=str(Path(__file__).resolve().parent),
    )


def _print_block(block) -> None:
    """يطبع كتلة محتوى واحدة بشكل مقروء."""
    if isinstance(block, TextBlock):
        text = (block.text or "").strip()
        if text:
            print(text)
    elif isinstance(block, ToolUseBlock):
        print(f"  ⚙️  [tool] {block.name}  ← {_short(block.input)}")
    elif isinstance(block, ToolResultBlock):
        print(f"  ↩️  [result] {_short(block.content)}")


def _short(value, limit: int = 220) -> str:
    """يقصّ قيمة طويلة لعرض تقدّم مقروء (ليس بيانات نهائية — عرض فقط)."""
    s = str(value).replace("\n", " ⏎ ")
    return s if len(s) <= limit else s[:limit] + " …"


async def run(task: str) -> int:
    """يشغّل الوكيل على مهمة نصّية ويطبع التقدّم. يعيد رمز خروج."""
    options = build_options()
    print("▶️  تشغيل وكيل test-fixer (repair agent) …\n")

    async for message in query(prompt=task, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                _print_block(block)
        elif isinstance(message, ResultMessage):
            print("\n" + "─" * 60)
            print("✅ انتهى التشغيل · run complete")
            # حقول التكلفة/الدورات اختيارية عبر الإصدارات؛ نعرضها إن وُجدت.
            cost = getattr(message, "total_cost_usd", None)
            turns = getattr(message, "num_turns", None)
            is_error = getattr(message, "is_error", False)
            if turns is not None:
                print(f"   الدورات · turns: {turns}")
            if cost is not None:
                print(f"   التكلفة · cost: ${cost:.4f}")
            if is_error:
                print("   ⚠️  انتهى بحالة خطأ · ended with error")
                return 1
    return 0


def main() -> int:
    # المهمة الافتراضية: أصلح أوّل فشل هرمتي. أو مرّر مهمة مخصّصة كوسيط.
    default_task = (
        "شغّل المجموعة الهرمتية بـ `python3 -m pytest -x -q --tb=short`، اعزل أوّل "
        "فشل، أصلِح المصدر (لا الاختبار إلا إذا ثبت عيبه)، أعد تشغيل الاختبار المعزول "
        "ثم المجموعة كاملة، والتزم حرفياً بقوانين عدم الاختلاق وعدم لمس "
        "requirements.txt أو migrations/. ثم لخّص ما أُصلِح وما تعذّر."
    )
    task = sys.argv[1] if len(sys.argv) > 1 else default_task
    return anyio.run(run, task)


if __name__ == "__main__":
    raise SystemExit(main())
