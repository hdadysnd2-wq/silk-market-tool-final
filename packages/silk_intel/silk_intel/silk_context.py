"""سياق التعميق — the /deepen execution context (stdlib contextvars).

الموجة ٢: الحصر البنيوي للوكلاء المدفوعين. `BaseAgent` يرفض تشغيل وكيل
`PAID=True` ما لم يكن السياق مفعّلاً — فلا يعتمد المنع على تذكُّر إضافة حارس
في api.py (درس الثغرات الثلاث التاريخية "استدعاء مدفوع تلقائي").

contextvars (لا متغير وحدة عام) حتى يبقى العزل صحيحاً مع تعدد الطلبات
المتزامنة في FastAPI. صفر تبعيات، صفر شبكة.
"""
from __future__ import annotations

import contextlib
import contextvars

_deepen: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "silk_deepen", default=False)


def deepen_active() -> bool:
    """هل نحن داخل تعميق؟ — True only inside a deepen_context() block."""
    return _deepen.get()


@contextlib.contextmanager
def deepen_context():
    """فعّل سياق التعميق — activate the paid-layer context for a with-block.

    يستخدمه مسار `/deepen` في api.py (والمكتبيون المباشرون عند الحاجة الصريحة).
    """
    token = _deepen.set(True)
    try:
        yield
    finally:
        _deepen.reset(token)


# حجب إضافات كلود (مراجعة المشروع، H2): استخلاص ثقافة المستهلك وفلترة
# الكيانات نداءاتُ كلود تجري على مسار /analyze المجاني — خارج وكلاء PAID
# الثلاثة فلا يمسكها حارس BaseAgent. هذا السياق يحجبها بنيوياً حين يقرّر
# api.py ذلك (مفتاح Anthropic بلا SILK_API_KEY، أو السقف اليومي مستنفد)،
# فتتدهور الطبقات إلى مسارها الكيليسي المعهود (لا اختلاق، الغياب مُعلَن).
_ai_extras_blocked: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "silk_ai_extras_blocked", default=False)


def ai_extras_blocked() -> bool:
    """هل إضافات كلود محجوبة؟ — True only inside a block_ai_extras() block."""
    return _ai_extras_blocked.get()


@contextlib.contextmanager
def block_ai_extras():
    """احجب إضافات كلود للكتلة — silk_ai_judge.available() يعيد False داخلها."""
    token = _ai_extras_blocked.set(True)
    try:
        yield
    finally:
        _ai_extras_blocked.reset(token)


# توجيهات الوكلاء (P3): درج «إعدادات الوكلاء» بالواجهة يرسل agent_prefs
# — {agent_key: {on: bool, cmd: str}}. الأمر النصي يوجّه **تركيز** برومبتات
# كلود حصراً (يُلحق داخل عزل _isolate القائم)؛ لا يصل أي وكيل بيانات رقمي
# ولا يستطيع توليد رقم — الثابت التأسيسي محفوظ بنيوياً.
_agent_prefs: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "silk_agent_prefs", default=None)


def agent_pref(agent_key: str) -> dict:
    """تفضيل وكيل واحد — {} حين لا سياق/لا تفضيل (السلوك الافتراضي)."""
    prefs = _agent_prefs.get() or {}
    p = prefs.get(agent_key)
    return p if isinstance(p, dict) else {}


def agent_command(agent_key: str) -> str:
    """أمر المستخدم النصي لوكيل — "" افتراضياً؛ مقصوص لطول آمن."""
    return str(agent_pref(agent_key).get("cmd") or "")[:500].strip()


def agent_enabled(agent_key: str) -> bool:
    """هل الوكيل مفعّل؟ — True افتراضياً (غياب التفضيل لا يعطّل شيئاً)."""
    p = agent_pref(agent_key)
    return bool(p.get("on", True))


@contextlib.contextmanager
def agent_prefs_context(prefs: dict | None):
    """فعّل تفضيلات الوكلاء للكتلة — contextvar بنمط deepen_context نفسه."""
    token = _agent_prefs.set(prefs if isinstance(prefs, dict) else None)
    try:
        yield
    finally:
        _agent_prefs.reset(token)


# إسناد التكلفة لكل بعثة (تدقيق تخفيض كلفة /research، Part C): كان
# record_llm_usage يُجمِّع الرموز حسب النموذج فقط — والاثنتا عشرة بعثة
# تتشارك نفس النموذج (Opus) اليوم، فلا سبيل لمعرفة أيّ بعثة استهلكت كم رمزاً
# من `llm_usage` وحده، ولا حدث تتبّع (`silk_trace`) يحمل عدّ رموز إطلاقاً
# (elapsed_ms/tool_calls فقط) — قرار توجيه نموذج لكل بعثة (Haiku مقابل Opus)
# يحتاج بالضبط هذا الرقم ولم يكن موجوداً. contextvar بنفس نمط agent_prefs
# أعلاه — ينسخه `contextvars.copy_context()` مستقلاً لكل خيط بعثة موازٍ
# (`run_all_missions`)، فلا تختلط بعثتان متزامنتان.
_current_mission: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "silk_current_mission", default=None)


@contextlib.contextmanager
def mission_context(mission_key: str | None):
    """فعّل وسم البعثة الحالية لكتلة — نداءات كلود داخلها تُسجَّل أيضاً في
    `data_counter()["mission_usage"][mission_key]` (راجع `record_llm_usage`)،
    فوق `llm_usage` الإجمالي القائم — لا يغيّره ولا يستبدله."""
    token = _current_mission.set(mission_key)
    try:
        yield
    finally:
        _current_mission.reset(token)


def current_mission() -> str | None:
    """مفتاح البعثة النشطة الآن — None خارج `mission_context` (نداءات
    المحلل/الكاتب/المراجع، التي ليست بعثة واحدة من الاثنتي عشرة)."""
    return _current_mission.get()


# اقتصاد البيانات (persist-5): عدّاد لكل تحليل — كم قراءة خُدمت من المخزن/
# ذاكرة الطلبات مقابل كم جلبة حية. contextvar فيعزل الطلبات المتزامنة؛
# غياب العدّاد (نداء مكتبي خارج analyze) = لا عدّ، صفر أثر على أي مسار.
# Per-analysis data-economics counter: store/cache hits vs live fetches.
_data_counter: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "silk_data_counter", default=None)


def begin_data_counter() -> dict:
    """ابدأ عدّاداً جديداً — fresh counter for this analysis run (contextvar).

    `llm_calls`/`tool_calls` (V5 wave 1): كل نداء كلود ونداء أداة داخل حلقة
    الوكيل اللغوي (`silk_llm_runtime.run_llm_agent`) يُعدّ هنا — نفس القناة
    الجانبية الصامتة لعدّادات المخزن/الجلب الحي، صفر أثر خارج تحليل نشط.

    `llm_usage` (تدقيق المعمارية، دين ٤): رموز الإدخال/الإخراج الفعلية لكل
    نموذج — يغذّي تقدير التكلفة (`silk_pricing.estimate_cost_usd`)؛ نفس مبدأ
    القناة الجانبية الصامتة — راجع `record_llm_usage`.

    `mission_usage` (Part C، إسناد التكلفة لكل بعثة): يُنشَأ كسولاً (lazy) في
    `record_llm_usage` فقط داخل `mission_context()` — {mission_key: {model:
    {tokens}}}؛ إضافي فوق `llm_usage` الإجمالي لا بديل عنه.
    """
    c = {"store_hits": 0, "cache_hits": 0, "live_fetches": 0,
         "llm_calls": 0, "tool_calls": 0, "llm_usage": {}}
    _data_counter.set(c)
    return c


def count_data(kind: str, n: int = 1) -> None:
    """سجّل حدث بيانات — increment a counter kind; silent no-op without one."""
    c = _data_counter.get()
    if c is not None and kind in c:
        c[kind] += n


def record_llm_usage(model: str, input_tokens: int, output_tokens: int,
                     cache_read_tokens: int = 0,
                     cache_creation_tokens: int = 0) -> None:
    """سجّل استهلاك رموز نداء كلود لكل نموذج — silent no-op outside an active
    counter (نفس نمط count_data). يستدعيها `silk_llm_provider` بعد كل رد
    ناجح يحمل حقل usage — لا يغيّر عقد أي دالة نداء قائمة (قناة جانبية فقط).

    `cache_read_tokens`/`cache_creation_tokens` (Prompt Caching): تُقرأان من
    `usage.cache_read_input_tokens`/`usage.cache_creation_input_tokens` في رد
    Anthropic — اختياريتان، تبقى القيمة الافتراضية صفراً لأي نداء بلا كاش."""
    c = _data_counter.get()
    if c is None:
        return

    def _add(row: dict) -> None:
        row["input_tokens"] += int(input_tokens or 0)
        row["output_tokens"] += int(output_tokens or 0)
        # الحقلان الاختياريان يُضافان فقط عند وجود كاش فعلي — نداء بلا كاش يُبقي
        # الصف بشكله الأصلي {input_tokens, output_tokens} كي لا يخالف اختبارات
        # المساواة الحرفية القائمة (regression guard).
        cr = int(cache_read_tokens or 0)
        cc = int(cache_creation_tokens or 0)
        if cr:
            row["cache_read_tokens"] = row.get("cache_read_tokens", 0) + cr
        if cc:
            row["cache_creation_tokens"] = row.get("cache_creation_tokens", 0) + cc

    usage = c.setdefault("llm_usage", {})
    _add(usage.setdefault(model, {"input_tokens": 0, "output_tokens": 0}))

    # إسناد لكل بعثة (Part C) — إضافي بحت، فوق `llm_usage` الإجمالي أعلاه لا
    # بدلاً منه. لا أثر خارج `mission_context` (نداءات المحلل/الكاتب/المراجع).
    mkey = _current_mission.get()
    if mkey is not None:
        m_usage = c.setdefault("mission_usage", {}).setdefault(mkey, {})
        _add(m_usage.setdefault(model, {"input_tokens": 0, "output_tokens": 0}))


def data_counter() -> dict | None:
    """العدّاد الحالي — the active counter dict, or None outside an analysis."""
    return _data_counter.get()


def snapshot_research_progress(analysis_id: int | None, stage: str,
                               started_at: str | None = None) -> None:
    """سجّل لقطة تقدّم حيّة لتشغيلة `/research` جارية — المرحلة الحالية +
    العدّادات الموجودة أصلاً (llm_calls/tool_calls) + تكلفة مُقدَّرة حتى
    الآن، محسوبة من نفس `data_counter()`/`silk_pricing.estimate_cost_usd`
    المستعمَلين للتقرير النهائي — **لا عدّاد جديد**، قراءة لِما هو مُتراكم
    فعلاً وقت الاستدعاء.

    قناة جانبية صامتة تماماً (نفس فلسفة `count_data`/`record_llm_usage`):
    بلا `analysis_id` (تشغيلة غير محفوظة، `persist=False`) أو عدّاد نشط
    = لا شيء؛ فشل الكتابة إلى القرص لا يُسقط التشغيلة أبداً (يُسجَّل تحذيراً
    فقط) — التقدّم المرئي تحسين، لا شرط تشغيل.
    """
    if analysis_id is None:
        return
    try:
        import silk_storage
        from silk_pricing import estimate_cost_usd
        c = _data_counter.get() or {}
        cost = estimate_cost_usd(c.get("llm_usage"))
        silk_storage.update_research_progress(
            analysis_id, stage=stage, started_at=started_at,
            llm_calls=c.get("llm_calls", 0), tool_calls=c.get("tool_calls", 0),
            cost_usd_estimate=cost["total_usd"],
            cost_unpriced_models=cost.get("unpriced_models") or [])
    except Exception as e:  # noqa: BLE001 — لقطة تحسينية، لا تُسقِط التشغيلة أبداً
        import logging
        logging.getLogger(__name__).warning(
            "progress snapshot failed for analysis %s stage %s: %s",
            analysis_id, stage, e)
