"""التوليف ثنائي المرحلة لسِلك — Silk two-stage synthesis (wave 4, vision §5, §9.3).

يوحّد طبقتي الحكم اللتين كانتا متوازيتين (ازدواجية حذفتها هذه الموجة):
  المرحلة ١ (حتمية): تجميع تقارير الوكلاء بقرار قابل للتفسير — منطق
    `JuryCommittee` نفسه (يبقى في silk_agents كمكوّن المرحلة ١).
  المرحلة ٢ (كلود، اختيارية بمفتاح): حكم فوق حقائق المرحلة ١ المعزولة؛
    وعند وجود **خيوط التقاطع** (بطاقة منتج) يتغيّر البرومبت إلى "مواجهة
    محددة": منتج المستخدم ضد المنافسين المرصودين (vision §5).

كل نص خارجي — حقائق الوكلاء والخيوط — يمرّ عبر عزل `RAW_FINDINGS` القائم
في silk_ai_judge (نفس آلية الموجة ٠، لا آلية جديدة). فشل تفسير ردّ كلود
=> `verdict: null` (قاعدة الموجة ١ — لا وسم مختلق).

نقطة الدخول الوحيدة للحكم: `synthesize()` — المحرّك لا يستدعي بعد اليوم
لجنةً وحكماً منفصلين (الازدواجية محذوفة، §9.3؛ إصلاح الحقن/الثقة يقع هنا
مرة واحدة).
"""
from __future__ import annotations

import json
import logging

from silk_agents import JuryCommittee
from silk_ai_judge import _call, _facts, _isolate, _user_steer, _PRINCIPLE

log = logging.getLogger(__name__)

# برومبت المواجهة (vision §5) — the confrontation prompt when threads exist.
_CONFRONTATION = (
    "أمامك مواجهة محددة — منتج المستخدم (بطاقته ضمن الخيوط المرفقة) ضد "
    "المنافسين المرصودين في الخيوط. احكم على المواجهة: مَن يستطيع المستخدم "
    "منافسته سعرياً ومن لا (استشهد بهوامش الخيوط حرفياً)، وما استراتيجية "
    "الدخول الواقعية عبر الأبواب المرصودة. كل رقم تذكره يجب أن يكون وارداً "
    "في الخيوط — الخيط الناقص يُذكر ناقصاً."
)


def _stage2(product: str, market: str, reports: list,
            threads: dict | None, instruction: str = "",
            analyst_assessment: dict | None = None) -> dict | None:
    """المرحلة ٢ — حكم كلود المعزول — Claude's judgment over isolated inputs.

    None عند غياب المفتاح/فشل النداء (المرحلة ١ تكفي وحدها حينها).
    `instruction`: توجيه المستخدم من لوحة «إعدادات الوكلاء» (صف «حكم
    التوليف») — يُلحق داخل العزل ويوجّه التركيز فقط، لا يتجاوز الحقائق.
    `analyst_assessment`: خرْج المحلل الشامل (الطبقة ٣، الموجة ٣ —
    `silk_market_analyst.to_synthesis_input`) — خمس تقاطعات + SWOT، يُلحق
    كسياق معزول إضافي؛ لا يستبدل حقائق الوكلاء الخام ولا خيوط التقاطع.
    """
    facts = _isolate(_facts(reports))
    # market يُعزل كسائر الحقول (مراجعة المشروع) — اتساق العزل لا يستثني حقلاً.
    parts = [f"المنتج: {_isolate(product)}", f"السوق: {_isolate(market)}", "",
             f"حقائق الوكلاء (لا تتجاوزها):\n{facts}"]
    if threads:
        blob = json.dumps(threads, ensure_ascii=False, default=str)
        parts += ["", "خيوط التقاطع (منتج المستخدم ضد المنافسين المرصودين):",
                  _isolate(blob), "", _CONFRONTATION]
    else:
        parts += ["", "أصدر حكمًا أوّليًّا على دخول هذا السوق."]
    if analyst_assessment:
        blob = json.dumps(analyst_assessment, ensure_ascii=False, default=str)
        parts += ["", "تقييم المحلل الشامل (الطبقة ٣ — خمس تقاطعات مبنية "
                  "على الأدلة + SWOT، زِنها في حكمك ولا تنسخها حرفياً):",
                  _isolate(blob)]
    parts += ["", 'أعد JSON فقط بهذا الشكل:',
              '{"verdict":"GO|WATCH|NO-GO","confidence":0.0-1.0,'
              '"reasoning":"سبب موجز مبني على الحقائق والخيوط"}'
              + _user_steer("synthesis", instruction)]
    out = _call(_PRINCIPLE, "\n".join(parts), max_tokens=900)
    if not out:
        return None
    try:
        start, end = out.find("{"), out.rfind("}")
        obj = (json.loads(out[start:end + 1]) if start >= 0
               else {"reasoning": out})
    except Exception:  # noqa: BLE001 — non-JSON reply kept as reasoning
        obj = {"reasoning": out}
    # قاعدة الموجة ١: لا افتراض وسم — فشل التفسير يعني verdict=None صريحًا.
    return {
        "verdict": obj.get("verdict"),
        "confidence": obj.get("confidence"),
        "reasoning": obj.get("reasoning", ""),
        "by": "تقييم الذكاء الاصطناعي",
        "preliminary": True,
        "grounded_in_threads": bool(threads),
        "grounded_in_analyst": bool(analyst_assessment),
    }


def synthesize(reports: list, *, product: str, market: str,
               threads: dict | None = None, with_ai: bool = False,
               instruction: str = "",
               analyst_assessment: dict | None = None) -> dict:
    """التوليف الموحّد — the single verdict entry point (both stages).

    يعيد بنية «jury» المتوافقة مع الواجهة القائمة (شرط ٩.٣: الحذف لا يغيّر
    شكل الاستجابة): مفاتيح المرحلة ١ كما كانت + `ai` للمرحلة ٢ إن توفرت.
    صف «حكم التوليف» في لوحة إعدادات الوكلاء: تعطيلُه يوقف المرحلة ٢ (كلود)
    فقط — المرحلة ١ الحتمية لا تُطفأ أبداً؛ وأمرُه النصي يوجّه تركيز الحكم.
    `analyst_assessment`: مُدخَل اختياري من المحلل الشامل (الطبقة ٣، الموجة
    ٣) — يصل المرحلة ٢ فقط إن with_ai، ولا يؤثر على المرحلة ١ الحتمية.
    """
    verdict = JuryCommittee.evaluate(reports)          # المرحلة ١ — حتمية
    verdict["synthesis_stage"] = 1
    import silk_context
    if with_ai and not silk_context.agent_enabled("synthesis"):
        verdict["ai_note"] = ("حكم كلود (المرحلة ٢) معطّل من إعدادات "
                              "الوكلاء — اكتفي بالمرحلة الحتمية")
        with_ai = False
    if with_ai:
        try:
            ai = _stage2(product, market, reports, threads, instruction,
                        analyst_assessment)
        except Exception as e:  # noqa: BLE001 — AI stage must never crash
            log.warning("synthesis stage 2 failed for %s: %s", market, e)
            ai = None
        if ai:
            verdict["ai"] = ai
            verdict["synthesis_stage"] = 2
    return verdict
