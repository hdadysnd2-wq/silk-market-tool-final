"""وكلاء البحث الثمانية والمنسّق — Silk research agents & orchestrator (Stage 3, §4b).

الطبقة بين خط البيانات (§4) ومحرك القرار (§8): الجامعون يملؤون مخزن الحقائق →
الوكلاء يقرؤون الحقائق (+ نداءات حية مستهدفة ضمن الميزانية) → المنسّق يتحقق من
المخطط ويجمّع → محرك القرار (Stage 4) يستهلك مدخلات الأعمدة → التقرير يستهلك
مخرجات الأقسام.

الثمانية (خطة §4b الخمسة + ثلاثة من توجيه المالك — آخرها اللوجستيات):
  market_size · competitor (طبقتان: دول + شركات) · regulatory ·
  pricing (طبقتان: حدودية + تجزئة) · risk · consumer_demand · supplier ·
  logistics (زمن التوريد + جسر التكلفة حتى الوصول للطبقة المدفوعة)

عقيدة المخطط تُفرَض بالتحقق (pydantic) لا بالمراجعة:
  * كل اكتشاف بقيمة يتطلب sources[] غير فارغة — لا رقم بلا مصدر.
  * modeled=True يتطلب formula صريحة — لا نموذج بلا معادلة معلنة.
  * قيمة غائبة = بند في gaps[] — الفجوة تُعلَن ولا تُخفى.
  * اكتشاف يخالف المخطط يُرفض عند التحقق ويُخفَّض إلى فجوة مسجَّلة — لا يصل
    التقرير ولا محرك القرار غير موثَّق.

كل الوكلاء الثمانية PAID=False (بروتوكول النقاط الأربع): المسار المدفوع الوحيد
هو طبقة التجزئة المهيكلة في pricing، وهي تفوّض LocalPriceAgent القائم الذي
يستحيل تنفيذه خارج /deepen بحارس BaseAgent البنيوي — خارج السياق تظهر فجوة
معلنة تشرح ذلك، بلا أي نداء.
"""
from __future__ import annotations

import concurrent.futures as _cf
import csv
import datetime
import json
import logging
import os
import time as _time

from pydantic import BaseModel, Field, field_validator, model_validator

from silk_agents import AgentReport, BaseAgent
from silk_data_layer import DataPoint, _today

log = logging.getLogger(__name__)

SCHEMA = "silk.research/v1"
# مهلة المنسّق لكل سوق — خُفِّضت من 90s إلى 45s: وكيلٌ بطيء (Trends/FAOSTAT
# محدودة المعدّل) كان يحتجز 90s فيبطئ التحليل بشدّة؛ 45s تكفي المصادر السليمة
# والبطيء يُعلَن فجوةً. قابلة للضبط عبر SILK_AGENT_TIMEOUT.
DEFAULT_TIMEOUT = float(os.environ.get("SILK_AGENT_TIMEOUT", "45"))
_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


# ── مخطط المخرجات · output schema (§4b, validated) ──────────────────────────

class SourceRef(BaseModel):
    """مرجع مصدر واحد لاكتشاف — one provenance reference for a finding."""

    source: str = Field(min_length=1)
    retrieved_at: str = ""
    confidence: float = 0.0
    url: str | None = None


class Finding(BaseModel):
    """اكتشاف واحد — metric + value + provenance; the doctrine is validated here."""

    metric: str = Field(min_length=1)
    value: object = None
    unit: str | None = None
    modeled: bool = False
    formula: str | None = None
    sources: list[SourceRef] = Field(default_factory=list)
    note: str = ""

    @model_validator(mode="after")
    def _doctrine(self):
        if self.value is not None and not self.sources:
            raise ValueError(
                "finding with a value requires non-empty sources[] — لا رقم بلا مصدر")
        if self.modeled and not (self.formula or "").strip():
            raise ValueError(
                "modeled finding requires an explicit formula — لا نموذج بلا معادلة")
        return self


class AgentOutput(BaseModel):
    """مخرجات وكيل واحد — the §4b envelope; invalid findings never enter it."""

    agent: str
    hs6: str = ""
    iso3: str = ""
    status: str = "failed"
    findings: list[Finding] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    rejected: list[str] = Field(default_factory=list)
    coverage: float = 0.0
    started_at: str = ""
    finished_at: str = ""

    @field_validator("status")
    @classmethod
    def _status(cls, v):
        if v not in ("complete", "partial", "failed"):
            raise ValueError("status must be complete|partial|failed")
        return v


def _src(source: str, conf: float = 0.9, url: str | None = None,
         retrieved_at: str | None = None) -> dict:
    return {"source": source, "confidence": conf, "url": url,
            "retrieved_at": retrieved_at or _today()}


def _dp_src(dp: DataPoint) -> dict:
    return {"source": dp.source, "confidence": dp.confidence,
            "retrieved_at": dp.retrieved_at or _today()}


def _f(metric: str, value, sources: list[dict], unit: str | None = None,
       modeled: bool = False, formula: str | None = None, note: str = "") -> dict:
    return {"metric": metric, "value": value, "unit": unit, "modeled": modeled,
            "formula": formula, "sources": sources, "note": note}


_TRIANGULATION_THRESHOLD_PCT = 20.0   # نفس عتبة تباين المصادر القائمة (Stage 2A xval)


def _triangulate(primary: DataPoint | None, mirror: DataPoint | None,
                 threshold_pct: float = _TRIANGULATION_THRESHOLD_PCT) -> dict:
    """ثلّث حقيقة بين مصدرين مستقلَّين — reconcile two independently-sourced
    observations of the same fact (mirror-statistics technique, §4b توسعة).

    لا يخترع قيمة موحّدة أبداً: القيمة المعروضة هي الأساسية (primary) دوماً؛
    الاتفاق/التباين يُعلَن في الملاحظة والمصدرين معاً يظهران في sources[]
    (فيستحيل بنيوياً إخفاء التباين). عند التباعد >العتبة تُخفَّض ثقة الأساسية
    (لا تُحذف) — إشارة جودة صادقة لا حكماً صامتاً. غياب أحدهما = مصدر واحد
    موسوم «غير مثلَّث»؛ غيابهما معاً = None (فجوة معلنة كالمعتاد).
    """
    have_p = primary is not None and primary.value is not None
    have_m = mirror is not None and mirror.value is not None
    if not have_p and not have_m:
        return {"value": None, "sources": [], "note": "", "divergence_pct": None}
    if have_p and not have_m:
        return {"value": primary.value,
                "sources": [_src(primary.source, primary.confidence,
                                 retrieved_at=primary.retrieved_at)],
                "note": "غير مثلَّث — تقرير سعودي مباشر (مرآة) غير متاح"
                        + (f": {mirror.note}" if mirror and mirror.note else ""),
                "divergence_pct": None}
    if have_m and not have_p:
        return {"value": mirror.value,
                "sources": [_src(mirror.source, mirror.confidence,
                                 retrieved_at=mirror.retrieved_at)],
                "note": "غير مثلَّث — تقرير الجهة المستوردة غير متاح؛ القيمة من "
                        "التقرير السعودي المباشر (مرآة)", "divergence_pct": None}
    p, m = float(primary.value), float(mirror.value)
    div = round(100 * abs(p - m) / max(abs(p), abs(m), 1e-9), 1)
    agree = div <= threshold_pct
    conf_p = primary.confidence if agree else min(primary.confidence, 0.6)
    note = (f"مثلَّث: يتفق تقرير الجهة المستوردة مع التقرير السعودي المباشر "
            f"(مرآة) — تباين {div}%"
            if agree else
            f"تباين تثليث {div}%: تقرير الجهة المستوردة مقابل التقرير السعودي "
            "المباشر (مرآة) — القيمة المعروضة من تقرير الجهة المستوردة، "
            "التباين معلن ولم يُسوَّ")
    return {"value": primary.value,
            "sources": [_src(primary.source, conf_p,
                             retrieved_at=primary.retrieved_at),
                       _src(mirror.source, mirror.confidence,
                            retrieved_at=mirror.retrieved_at)],
            "note": note, "divergence_pct": div, "agree": agree}


_PHASE2_CONF_CAP = 0.5              # سقف ثقة أي تقدير مثلَّث متعدد الإشارات
_PHASE2_CONFLICT_THRESHOLD_PCT = 30.0  # عتبة تعارض «الرقم الرسمي يفوز» (§7)


def _trends_series(product: str | None, geo: str | None) -> dict | None:
    """غلاف نداء تريندز واحد — حارس ميزانية المرحلة ٢: لا يُستدعى إلا عند
    فجوة مصدر رسمي، ونتيجته الواحدة تُشارَك بين أكثر من مقياس بديل بلا
    تكرار (النمو ومؤشر النشاط كلاهما يقرآن من نفس هذا النداء)."""
    if not (product or "").strip():
        return None
    from silk_trends_agent import trends_series
    return trends_series(product, geo)


def _triangulate_estimate(metric: str, official: DataPoint | None,
                          estimate_value, estimate_sources: list[dict],
                          estimate_formula: str, estimate_note: str,
                          *, threshold_pct: float = _PHASE2_CONFLICT_THRESHOLD_PCT,
                          cap: float = _PHASE2_CONF_CAP,
                          unit: str | None = None) -> dict | None:
    """رسمي أولاً، تقدير مثلَّث احتياطي معلن (Stage 3 المرحلة ٢، §7).

    مصادر تعدد الإشارات (Serper/Maps/Trends) عند فجوة مصدر رسمي (كومتريد/
    WITS/FAOSTAT). يعيد اكتشافاً جاهزاً لـ `_f()` أو None (فجوة تُترَك
    للمستدعي). **لا دمج قيمتين أبداً**: المعروض رسمي عند توفّره حصراً
    (وثقته الأصلية)، أو تقدير مُعلَن `modeled=True` بثقة مسقوفة عند 0.5
    (`cap`) عند غياب الرسمي فقط، أو لا شيء عند غياب الاثنين. تعارض >30%
    بينهما لا يُخفي أياً منهما — الرسمي يعرض قيمته وملاحظة التعارض معاً.
    """
    have_o = official is not None and official.value is not None
    have_e = estimate_value is not None and bool(estimate_sources)
    if not have_o and not have_e:
        return None
    if have_o and not have_e:
        return _f(metric, official.value,
                  [_src(official.source, official.confidence,
                       retrieved_at=official.retrieved_at)],
                  unit=unit, note=official.note)
    capped = [dict(s, confidence=min(s.get("confidence", cap), cap))
             for s in estimate_sources]
    if have_e and not have_o:
        return _f(metric, estimate_value, capped, unit=unit, modeled=True,
                  formula=estimate_formula,
                  note=f"تقدير مثلَّث (لا رقم رسمي متاح) — سقف ثقة {cap} — "
                       f"{estimate_note}")
    o, ev = float(official.value), float(estimate_value)
    div = round(100 * abs(o - ev) / max(abs(o), abs(ev), 1e-9), 1)
    conflict = (f" — تعارض {div}% مع تقدير مثلَّث ({ev}) عبر إشارات مستقلة؛ "
               f"الرقم الرسمي معروض وله الأولوية (قاعدة المرحلة ٢، §7)"
               if div > threshold_pct else
               f" — يتفق مع تقدير مثلَّث مستقل (تباين {div}%)")
    return _f(metric, official.value,
              [_src(official.source, official.confidence,
                   retrieved_at=official.retrieved_at)],
              unit=unit, note=official.note + conflict)


def _mirror_dp_for(mirror_raw: DataPoint, value, note: str | None = None) -> DataPoint:
    """ابنِ DataPoint المرآة المشتقّ — يحافظ على ملاحظة فشل النداء الأصلية
    بدل فقدانها متى تعذّر اشتقاق المقياس (حصة/قيمة وحدة) من قيمتها الخام."""
    if value is not None:
        return DataPoint(value, mirror_raw.source, mirror_raw.confidence,
                         mirror_raw.note, mirror_raw.retrieved_at)
    if mirror_raw.value is None:
        return mirror_raw   # فشل النداء نفسه — ملاحظته الأصلية كافية ومفسِّرة
    return DataPoint(None, mirror_raw.source, 0.0,
                     note or "تعذّر اشتقاق القيمة من بيانات المرآة الخام",
                     mirror_raw.retrieved_at)


def _failed_output(agent: str, task: dict, reason: str) -> dict:
    """مغلّف فشل صريح — a failed envelope whose reason is visible, never silent."""
    now = _now_iso()
    return AgentOutput(
        agent=agent, hs6=str(task.get("hs6") or ""), iso3=str(task.get("iso3") or ""),
        status="failed", findings=[], gaps=[reason], coverage=0.0,
        started_at=now, finished_at=now).model_dump()


# ── الأساس المشترك · shared research-agent base ─────────────────────────────

class ResearchAgent(BaseAgent):
    """وكيل بحث §4b — يبني حول حرّاس BaseAgent البنيويين تحققَ المخطط والتغطية.

    الفئات الفرعية تكتب `_research(task) -> (raw_findings, gaps)` فقط؛ هنا:
    التحقق (اكتشاف مخالف => يُرفض ويُخفَّض إلى فجوة)، فرض «قيمة غائبة = فجوة
    معلنة»، حساب التغطية من EXPECTED، وتعليب المغلف الموحّد.
    """

    PAID = False               # الثمانية مجانية — المدفوع محصور في /deepen بنيوياً
    AGENT = ""                 # الاسم المخططي (market_size, competitor, …)
    EXPECTED: tuple[str, ...] = ()

    def __init__(self) -> None:
        super().__init__(self.__class__.__name__)

    def _research(self, task: dict) -> tuple[list[dict], list[str]]:
        raise NotImplementedError

    def _execute(self, task: dict) -> AgentReport:
        started = _now_iso()
        raw, gaps = self._research(task)
        findings: list[Finding] = []
        rejected: list[str] = []
        for rf in raw:
            try:
                findings.append(Finding(**rf))
            except Exception as e:  # noqa: BLE001 — رفض المخطط يُسجَّل لا يُبتلع
                msg = (f"{rf.get('metric', '?')}: rejected at schema validation — "
                       f"{e}")
                rejected.append(msg)
                gaps.append(msg)
                log.warning("%s: %s", self.AGENT, msg)
        for f in findings:  # قيمة غائبة بلا فجوة مقابلة => الفجوة تُضاف تلقائياً
            if f.value is None and not any(f.metric in g for g in gaps):
                gaps.append(f"{f.metric}: {f.note or 'غير مرصود — unobserved'}")
        observed = {f.metric for f in findings if f.value is not None}
        if self.EXPECTED:
            coverage = round(len(observed & set(self.EXPECTED))
                             / len(self.EXPECTED), 2)
        else:
            coverage = 1.0 if observed else 0.0
        status = ("failed" if not observed else
                  "complete" if coverage >= 0.999 and not gaps else "partial")
        out = AgentOutput(
            agent=self.AGENT, hs6=str(task.get("hs6") or ""),
            iso3=str(task.get("iso3") or ""), status=status, findings=findings,
            gaps=gaps, rejected=rejected, coverage=coverage,
            started_at=started, finished_at=_now_iso())
        return AgentReport(self.name, [out.model_dump()], failed=(status == "failed"),
                           summary=f"{self.AGENT}: {status} coverage={coverage}")


# ── ١) وكيل حجم السوق · market size (TAM/SAM/SOM + نمو) ─────────────────────

_TIER_FACTORS = {"premium": 0.2, "mid": 0.5, "standard": 0.5,
                 "mass": 0.8, "economy": 0.8}


class MarketSizeAgent(ResearchAgent):
    """TAM مرصود (كومتريد) · SAM/SOM نموذجان معلنا الافتراضات · نمو من المخزن."""

    AGENT = "market_size"
    PREF_KEY = "trade"
    EXPECTED = ("tam_usd", "import_growth_pct", "import_cagr_pct",
                "sam_usd", "som_usd")

    def _research(self, task):
        F: list[dict] = []
        gaps: list[str] = []
        hs, iso3, year = task["hs6"], task["iso3"], int(task["year"])
        from silk_data_layer_v2 import market_imports_cached
        mi = market_imports_cached(hs, task.get("m49"), iso3, year)
        tam = mi.get("total_usd")
        if tam is not None:
            F.append(_f("tam_usd", tam, [_src("UN Comtrade")], unit="USD",
                        note=f"TAM = إجمالي واردات السوق المرصودة HS{hs} سنة "
                             f"{year}{mi.get('xval_note') or ''}"))
        else:
            gaps.append(f"tam_usd: لا واردات مرصودة HS{hs} {iso3} {year} — "
                        "كومتريد غير متاح والمخزن بارد")

        # النمو من مخزن الحقائق حصراً (لا توسيع نداءات حية هنا — الميزانية للجامع).
        import silk_store
        from silk_trend import cagr_pct, growth_pct
        pairs: list[tuple[int, float | None]] = []
        for y in range(year - 4, year + 1):
            try:
                pairs.append((y, silk_store.market_imports_from_store(
                    hs, iso3, y)["total_usd"]))
            except Exception:  # noqa: BLE001 — المخزن تحسين لا شرط
                pairs.append((y, None))
        g, c = growth_pct(pairs), cagr_pct(pairs)
        obs_years = [y for y, v in pairs if v is not None]
        g_official = (DataPoint(g, "UN Comtrade (مخزن الحقائق)", 0.9,
                                f"نمو الواردات {obs_years[0]}→{obs_years[-1]} — "
                                f"{len(obs_years)}/5 سنوات مرصودة، الفجوات معلنة")
                     if g is not None else None)
        c_official = (DataPoint(c, "UN Comtrade (مخزن الحقائق)", 0.9,
                                f"CAGR عبر السنوات المرصودة "
                                f"{obs_years[0]}–{obs_years[-1]}")
                     if c is not None else None)

        # المرحلة ٢ (§7): فجوة النمو الرسمي (كومتريد بارد/محجوب) => تقدير
        # مثلَّث احتياطي من مسار Google Trends (ربع أول↔أخير من السلسلة
        # نفسها) — حارس ميزانية: نداء واحد فقط، ولا يُحاوَل إلا عند الفجوة.
        trend_sig = (_trends_series(task.get("product"), task.get("iso2"))
                    if (g is None or c is None) else None)
        tf_growth, tf_conf, tf_note = (
            (trend_sig or {}).get("growth_pct"), (trend_sig or {}).get("confidence", 0.0),
            (trend_sig or {}).get("note", ""))
        gf = _triangulate_estimate(
            "import_growth_pct", g_official, tf_growth,
            [_src("Google Trends", tf_conf)] if tf_growth is not None else [],
            "تقدير نمو مثلَّث = نسبة تغيّر متوسط اهتمام Google Trends بين الربع "
            "الأول والأخير من فترة الدراسة (بديل عن نمو الاستيراد الرسمي الغائب)",
            tf_note, unit="%")
        if gf:
            F.append(gf)
        else:
            gaps.append("import_growth_pct: يتطلب سنتين مرصودتين في مخزن "
                        "الحقائق أو إشارة Google Trends بديلة — كلاهما غائب "
                        f"({tf_note or 'تريندز لم يُحاوَل'})")
        if c_official is not None:
            F.append(_f("import_cagr_pct", c_official.value,
                        [_src(c_official.source, c_official.confidence)],
                        unit="%", note=c_official.note))
        else:
            gaps.append("import_cagr_pct: يتطلب سلسلة سنوات في مخزن الحقائق "
                        "— لا بديل مثلَّث مباشر لـCAGR")

        # market_activity_index (جديد، المرحلة ٢، §7): فجوة TAM الرسمية =>
        # مؤشر نشاط مثلَّث (كثافة تجزئة Google Maps + اهتمام Google Trends)،
        # 0..1، مُعلَن modeled بثقة مسقوفة 0.5 — لا يُقارَن بدولار TAM (وحدتان
        # مختلفتان تماماً)، بل يغذّي عمود جاذبية السوق كإشارة إضافية عند غياب
        # TAM (§8). حارس ميزانية: نداءا Maps/Trends يُحاولان فقط عند الفجوة،
        # ويُعاد استخدام نداء Trends السابق (trend_sig) دون تكراره.
        if tam is None:
            product, market_name = task.get("product", ""), task.get(
                "market_name", iso3)
            from silk_maps_agent import find_places
            places = ([p for p in find_places(
                f"{product} retailer store supermarket {market_name}")
                if p.value is not None] if product else [])
            trend_level = (trend_sig or {}).get("mean")
            idx_sources, idx_parts = [], []
            if places:
                idx_sources.append(_src("Google Maps", 0.5))
                idx_parts.append(min(len(places) / 10.0, 1.0))
            if trend_level is not None:
                idx_sources.append(_src("Google Trends", 0.5))
                idx_parts.append(trend_level / 100.0)
            idx_val = round(sum(idx_parts) / len(idx_parts), 2) if idx_parts else None
            mf = _triangulate_estimate(
                "market_activity_index", None, idx_val, idx_sources,
                "مؤشر نشاط مثلَّث = متوسط(كثافة تجزئة Google Maps المُطبَّعة "
                "(عدد الأماكن/10، سقف 1.0)، اهتمام Google Trends/100) — "
                "بديل جزئي غير دولاري عند غياب TAM الرسمي، لا يُقارَن به مباشرة",
                f"أماكن Google Maps={len(places)}؛ اهتمام Google Trends="
                f"{trend_level}", unit=None)
            if mf:
                F.append(mf)
            else:
                gaps.append("market_activity_index: Google Maps وGoogle "
                            "Trends كلاهما غير متاحين — لا بديل عن TAM الرسمي")

        # SAM/SOM — نموذجان بافتراضات معلنة (§7-2): لا يُحسبان بلا مدخلاتهما.
        card = task.get("product_card") or {}
        tier = str(card.get("tier") or "").strip().lower()
        if tam is not None and tier in _TIER_FACTORS:
            factor = _TIER_FACTORS[tier]
            F.append(_f("sam_usd", round(tam * factor), [_src("UN Comtrade")],
                        unit="USD", modeled=True,
                        formula=f"SAM = TAM × {factor} (عامل شريحة '{tier}' — "
                                "افتراض معلن قابل للتعديل)",
                        note="مُقدَّر — نموذج بافتراضات معلنة، ليس رصداً"))
        else:
            gaps.append("sam_usd: يتطلب TAM مرصوداً + شريحة tier في بطاقة المنتج "
                        "(premium/mid/mass)")
        cap = card.get("monthly_capacity")
        uv = _border_unit_value(hs, iso3, year)
        if cap and uv and tam is not None:
            som = round(min(tam * _TIER_FACTORS.get(tier, 1.0),
                            float(cap) * 12 * uv))
            F.append(_f("som_usd", som, [_src("UN Comtrade")], unit="USD",
                        modeled=True,
                        formula="SOM = min(SAM أو TAM، الطاقة الشهرية × 12 × "
                                f"قيمة الوحدة الحدودية {uv:.2f}$/kg)",
                        note="مُقدَّر — سقف إيراد الطاقة الإنتاجية بأسعار الحدود "
                             "المرصودة"))
        else:
            gaps.append("som_usd: يتطلب طاقة شهرية في بطاقة المنتج + قيمة وحدة "
                        "حدودية مرصودة (قيمة/وزن كومتريد)")
        return F, gaps


def _border_unit_value(hs: str, iso3: str, year: int) -> float | None:
    """قيمة الوحدة الحدودية $/kg من المخزن — value/qty of the WLD row, or None."""
    try:
        import silk_store
        row = silk_store.get_trade_flow(hs, iso3, "WLD", year)
        if row and row.get("value_usd") and row.get("qty_kg"):
            return row["value_usd"] / row["qty_kg"]
    except Exception:  # noqa: BLE001 — المخزن تحسين لا شرط
        pass
    return None


# ── ٢) وكيل المنافسة · competitor (طبقتان: دول ثم شركات) ────────────────────

class CompetitorAgent(ResearchAgent):
    """الطبقة ١: دول مورّدة بحصص وHHI (كومتريد). الطبقة ٢: شركات بالاسم
    (Serper/Maps) — مرشّحون غير موثَّقين برابط وتاريخ، ثقة 0.4، لا اختلاق."""

    AGENT = "competitor"
    PREF_KEY = "competition"
    EXPECTED = ("hhi", "top_supplier_share_pct", "saudi_share_pct",
                "supplier_countries", "named_companies")

    def _research(self, task):
        F: list[dict] = []
        gaps: list[str] = []
        hs, iso3, year = task["hs6"], task["iso3"], int(task["year"])
        from silk_data_layer_v2 import market_imports_cached
        mi = market_imports_cached(hs, task.get("m49"), iso3, year)
        comps = mi.get("competitors") or []
        if comps:
            rows = [c.value for c in comps if c.value]
            shares = [r["share"] for r in rows]
            hhi = round(sum((s / 100.0) ** 2 for s in shares), 3)
            ct = _src("UN Comtrade")
            F.append(_f("hhi", hhi, [ct],
                        note=f"مؤشر هيرفنداهل لتركّز المورّدين ({len(rows)} دولة) — "
                             ">0.25 سوق مركّز"))
            F.append(_f("top_supplier_share_pct", shares[0], [ct], unit="%",
                        note=f"حصة المورّد الأكبر: {rows[0]['partner']}"))
            # حصة السعودية مثلَّثة (تقنية إحصاءات المرآة، §4b توسعة): تقرير
            # الجهة المستوردة (partner=SAU ضمن صفوف التنافس) مقابل التقرير
            # السعودي المباشر (reporter=SAU، مرآة) — لا اختلاق، القيمة
            # المعروضة أساسية دوماً والاتفاق/التباين معلن بمصدرين معاً.
            sau = next((r for r in rows if str(r.get("code")) == "682"), None)
            grand = sum(r["value_usd"] for r in rows)
            target_dp = (DataPoint(sau["share"], "UN Comtrade", 0.9,
                                   "حصة السعودية بين المورّدين المبلَّغ عنهم",
                                   _today())
                        if sau else None)
            from silk_data_layer_v2 import mirror_saudi_export
            mirror_raw = mirror_saudi_export(hs, task.get("m49"), iso3, year)
            mval = ((mirror_raw.value or {}).get("value_usd")
                   if mirror_raw.value else None)
            mirror_share = (round(100 * mval / grand, 2)
                           if (mval is not None and grand) else None)
            mirror_dp = _mirror_dp_for(mirror_raw, mirror_share)
            tri = _triangulate(target_dp, mirror_dp)
            if tri["value"] is not None:
                F.append(_f("saudi_share_pct", tri["value"], tri["sources"],
                            unit="%", note=tri["note"]))
            else:
                gaps.append("saudi_share_pct: غير ظاهرة بين المورّدين المبلَّغ "
                           "عنهم ولا في التقرير السعودي المباشر (رصد غياب "
                           "مزدوج، ليس تقديراً)")
            F.append(_f("supplier_countries", rows[:8], [ct],
                        note=f"أكبر {min(8, len(rows))} دول مورّدة بالقيمة والحصة"))
        else:
            gaps.append(f"الطبقة الدولية: لا صفوف شركاء HS{hs} {iso3} {year} — "
                        "كومتريد غير متاح والمخزن بارد")

        # الطبقة ٢ — كيانات ومراجع (إصلاح مراجعة Stage 5، ثغرة ٢): أسماء الأعمال
        # الحقيقية تأتي من Google Places حصراً (kind=entity)؛ نتائج بحث الويب
        # عناوين صفحات لا أسماء كيانات فتُدرج «مرجعاً للمراجعة اليدوية»
        # (kind=reference) — لا يُعرض عنوان بحث كاسم منافس أبداً.
        product, market = task.get("product", ""), task.get("market_name", iso3)
        named, refs, dropped = _entities_and_references(
            web_queries=[f"top {product} brands importers distributors "
                         f"companies in {market}"],
            maps_query=f"{product} distributor importer {market}",
            product=product, market=market,
            role="موزّع أو مستورد أو شركة تجارية")
        drop_note = (f" · استُبعد {dropped} محل تجزئة/مطعم غير ذي صلة"
                     if dropped else "")
        if named:
            F.append(_f("named_companies", named, refs,
                        note="كيانات Google Maps بالاسم (○ غير متحقق) "
                             "+ مراجع ويب للمراجعة اليدوية — أكّدها قبل "
                             "الاعتماد؛ الترقية الموثّقة عبر خدمة التعميق "
                             "المدفوعة (Volza/Explee)" + drop_note))
        else:
            gaps.append(
                "الطبقة الاسمية (شركات): "
                + (f"استُبعدت {dropped} نتيجة تجزئة/مطعم غير ذات صلة — لا موزّع/"
                   "مستورد بالجملة مؤكّد عبر البحث المجاني؛ الأسماء الموثّقة "
                   "للمستوردين من السجلّات الجمركية عبر Volza/Explee (/deepen). "
                   if dropped else "تتطلب SEARCH_API_KEY و/أو GOOGLE_MAPS_API_KEY "
                   "في بيئة الخادم — لا أسماء مخترعة"))
        return F, gaps


_RETAIL_FOOD_SERVICE_TYPES = {
    "restaurant", "cafe", "meal_takeaway", "meal_delivery", "bakery",
    "convenience_store", "supermarket", "grocery_or_supermarket",
    "food", "bar", "night_club", "meal_kit_delivery",
}

# أنواع ليست موردَ سلعٍ بالجملة إطلاقاً — بلاغ المالك: «Ananas Insurance» و«محمصة
# أناناس» ظهرت كموردي أناناس. تصنيف Google لهذه (تأمين/عقار/مالية/صحة/تعليم/
# سياحة…) يكشفها فوراً حتى بلا كلود. Clearly not a wholesale goods supplier.
_NON_SUPPLIER_TYPES = _RETAIL_FOOD_SERVICE_TYPES | {
    "insurance_agency", "real_estate_agency", "finance", "bank", "atm",
    "accounting", "lawyer", "dentist", "doctor", "hospital", "pharmacy",
    "physiotherapist", "veterinary_care", "school", "primary_school",
    "secondary_school", "university", "gym", "beauty_salon", "hair_care",
    "spa", "lodging", "car_dealer", "car_repair", "car_rental",
    "gas_station", "travel_agency", "lawyer", "mosque", "church",
    "museum", "park", "tourist_attraction", "gym", "casino", "movie_theater",
    "clothing_store", "shoe_store", "jewelry_store", "electronics_store",
    "furniture_store", "book_store", "roasting", "coffee_shop",
}


def _business_hint(types: object) -> str | None:
    """تلميح نوع العمل من تصنيف جوجل الفعلي — لا يُفترض «موزّع/مستورد بالجملة»
    عن مكان تصنيفُه ليس مورّدَ سلعٍ (مطعم/مقهى/محل تجزئة/تأمين/عقار/مالية…).
    بلاغ المالك: محلُّ عصيرٍ وشركةُ تأمينٍ ظهرا كمستوردين. Google Places لا يملك
    تصنيفاً رسمياً لـ«موزّع بالجملة»، فلا نؤكِّد ذلك إيجاباً — بل نُعلِن ونستبعد
    حين يكون التصنيف بوضوحٍ غير موردِ سلع."""
    for t in (types or []):
        if t in _NON_SUPPLIER_TYPES:
            return "retail_or_food_service"
    return None


def _qualify_entities(raw: list[dict], product: str, market: str,
                      role: str) -> tuple[list[dict], int]:
    """يفلتر الوكيلُ المرشّحين بذكاء — the agent (Claude) judges each candidate:
    genuine wholesale `role` (keep) vs retail/food-service/irrelevant (drop).

    بلاغ المالك: «ليش أضفنا وكلاء عشان يفلترون النتائج» — الفلترة صارت **حُكم
    وكيلٍ ذكي** لا قائمةَ كلماتٍ ثابتة: كلود يصنّف كلَّ كيانٍ من اسمه/عنوانه/
    تصنيف جوجل، ويُبقي الموزّعين/المستوردين بالجملة الحقيقيين فقط. مبدأ لا-اختلاق
    محفوظ: يصنّف المعطى فقط، لا يخترع اسماً. بلا مفتاح كلود يتراجع للفلتر النوعي
    الثابت (تجزئة/مطعم) كأمانٍ كيليس. يعيد (المُبقَى، عدد المُستبعَد).
    """
    if not raw:
        return [], 0
    import silk_ai_judge as aij
    if not aij.available():
        # تراجع كيليس: فلتر النوع الثابت فقط.
        kept = [e for e in raw
                if _business_hint(e.get("types")) != "retail_or_food_service"]
        return kept, len(raw) - len(kept)
    raw = raw[:12]  # حدّ أعلى — لا نُثقل نداء الفلترة
    lines = []
    for i, e in enumerate(raw):
        lines.append(f"{i}. {e.get('name', '')} | العنوان: {e.get('address') or '؟'} "
                     f"| تصنيف Google: {', '.join(e.get('types') or []) or '؟'}")
    user = (
        f"المنتج: {aij._isolate(product or '؟')} — السوق: {aij._isolate(market or '؟')}.\n"
        f"المرشّحون (كيانات من خرائط Google):\n" + aij._isolate("\n".join(lines)) + "\n\n"
        f"أبقِ فقط مَن هو **{role} بالجملة حقيقي** لهذا المنتج. استبعِد: محلات "
        "التجزئة والمطاعم والمقاهي والمحامص، وأي كيان **ليس مورّد سلعٍ** (تأمين، "
        "عقار، مالية، عيادة، صالون، فندق…) حتى لو حمل اسمَ المنتج (مثلاً «Ananas "
        "Insurance» شركةُ تأمينٍ لا مورّدَ أناناس — استبعِدها). استند إلى المعطى "
        'فقط؛ عند الشكّ استبعِد. أعد **JSON فقط**: {"keep":[أرقام المُبقَين]}.')
    # نموذج سريع + مهلة قصيرة: الفلترة مهمّة خفيفة يجب ألّا تعلّق التحليل خلف Opus.
    raw_out = aij._call(
        "أنت مصنّف كيانات تجارية في منصة سِلك لتصدير المنتجات السعودية. لا تخترع "
        "أي اسم؛ صنّف المعطى فقط وأعد أرقام مَن يصلح موزّعاً/مستورداً بالجملة.",
        user, max_tokens=300, model=aij._FAST_MODEL, timeout=12)
    if not raw_out:
        return raw, 0
    try:
        s, e = raw_out.find("{"), raw_out.rfind("}")
        keep = set(int(x) for x in (json.loads(raw_out[s:e + 1]).get("keep") or [])
                   if isinstance(x, (int, float)))
        kept = [raw[i] for i in range(len(raw)) if i in keep]
        return kept, len(raw) - len(kept)
    except Exception as ex:  # noqa: BLE001 — bad JSON => keep all (no silent loss)
        log.warning("entity qualification parse failed: %s", ex)
        return raw, 0


def _entities_and_references(web_queries: list[str], maps_query: str,
                             region: str | None = None, num: int = 4,
                             product: str = "", market: str = "",
                             role: str = "موزّع أو مستورد"
                             ) -> tuple[list[dict], list[dict], int]:
    """مرشّحون مفصولون بالنوع — entities (Google Places names) vs references
    (web-result titles for manual review). عنوان بحث ليس اسم كيان (ثغرة ٢).

    الكياناتُ يفلترها **الوكيلُ الذكي** (`_qualify_entities`): يحكم كلود أيُّها
    موزّع/مستورد بالجملة حقيقي ويستبعد محلات التجزئة/المطاعم؛ بلا مفتاح يتراجع
    للفلتر النوعي الثابت. يُعاد عددُ المُستبعَد ليُعلَن؛ فإن فرَغت القائمة تُعلَن
    الفجوة وتُحال إلى المستوردين الموثّقين عبر Volza/Explee (سجلّات جمركية).
    """
    out, refs = [], []
    from silk_maps_agent import find_places
    from silk_websearch_agent import web_search
    raw = []
    for dp in find_places(maps_query, region=region):
        if dp.value:
            raw.append({"name": dp.value.get("name", ""),
                        "address": dp.value.get("address"),
                        "rating": dp.value.get("rating"),
                        "types": dp.value.get("types") or [],
                        "retrieved_at": dp.retrieved_at})
    kept, dropped_retail = _qualify_entities(raw, product, market, role)
    for e in kept:
        out.append({"kind": "entity", "name": e.get("name", ""),
                    "address": e.get("address"), "rating": e.get("rating"),
                    "business_hint": None,
                    "via": "Google Maps", "retrieved_at": e.get("retrieved_at")})
        refs.append(_src("Google Maps", 0.4, retrieved_at=e.get("retrieved_at")))
    # عناوينُ الويب تُجمَع مرّةً واحدة (كان يُكرَّر الحلقةُ فيتضاعف السرد)، بلا تكرار.
    web_raw, seen_urls = [], set()
    for q in web_queries:
        for dp in web_search(q, num):
            if not dp.value:
                continue
            link = dp.value.get("link", "")
            key = link or dp.value.get("title", "")
            if key in seen_urls:
                continue
            seen_urls.add(key)
            web_raw.append(dp)
    # الطبقة ٣: الوكيلُ (كلود) يستخلص أسماءَ الشركات من العناوين بدل سردِ روابطَ خام
    # (بلاغ المالك «ترسل روابط = أنت قوقل»). المُستخلَص يظهر كأسماءٍ غير موثَّقة؛
    # الروابطُ الخامُ تنزوي كاستشهادٍ محدود. بلا مفتاح: تبقى الروابطُ كمراجع كالسابق.
    extracted = None
    try:
        import silk_ai_judge as aij
        if aij.available() and web_raw:
            extracted = aij.extract_companies(
                [dp.value for dp in web_raw], product, market, role)
    except Exception as e:  # noqa: BLE001 — الاستخلاص اختياري لا يُعطِّل الوكيل
        log.warning("company extraction skipped: %s", e)
        extracted = None
    if extracted:
        for c in extracted:
            out.append({"kind": "entity", "name": c.get("name", ""),
                        "address": None, "rating": None, "business_hint": None,
                        "via": "Web → Claude", "url": c.get("url", ""),
                        "retrieved_at": _today(), "note": c.get("note", "")})
            refs.append(_src("Web Search → Claude", 0.4, url=c.get("url", "")))
        # استشهادٌ محدود: أوّل ٣ روابطَ خام تحت الأسماء المُستخلَصة (لا سردٌ طويل).
        for dp in web_raw[:3]:
            out.append({"kind": "reference", "title": dp.value.get("title", ""),
                        "url": dp.value.get("link", ""), "via": "Serper",
                        "retrieved_at": dp.retrieved_at,
                        "note": "مصدرُ الاستخلاص — للاستشهاد"})
    else:
        # تراجُع بلا مفتاح: الروابطُ الخامُ كمراجع (منزوعةُ التكرار الآن).
        for dp in web_raw:
            out.append({"kind": "reference", "title": dp.value.get("title", ""),
                        "url": dp.value.get("link", ""), "via": "Serper",
                        "retrieved_at": dp.retrieved_at,
                        "note": "مرجع للمراجعة اليدوية — ليس اسم كيان"})
            refs.append(_src("Web Search (Serper)", 0.3,
                             url=dp.value.get("link"),
                             retrieved_at=dp.retrieved_at))
    return out, refs, dropped_retail


# ── ٣) الوكيل التنظيمي · regulatory ──────────────────────────────────────────

class RegulatoryAgent(ResearchAgent):
    """قائمة الاشتراطات L1 (مرجع ساكن مُستشهَد) + التعريفة المطبّقة (WITS)."""

    AGENT = "regulatory"
    PREF_KEY = "regulatory"
    EXPECTED = ("requirements_checklist", "entry_requirements_count",
                "eligibility_gate", "tariff_applied_pct")

    def _research(self, task):
        F: list[dict] = []
        gaps: list[str] = []
        hs, iso3, year = task["hs6"], task["iso3"], int(task["year"])
        from silk_requirements_agent import RequirementsAgent
        rep = RequirementsAgent().run({"market_iso3": iso3, "hs_code": hs})
        items = [f.value for f in rep.findings if f.value is not None]
        if items:
            l1 = _dp_src(next(f for f in rep.findings if f.value is not None))
            F.append(_f("requirements_checklist", items, [l1],
                        note=f"{len(items)} بند اشتراطات (دخول السوق + خروج سعودي) "
                             "— كل بند بلائحته ورابطه الرسمي"))
            F.append(_f("entry_requirements_count", len(items), [l1],
                        note="عدد بنود قائمة التحقق"))
            gate = any("2017/625" in str(i) for i in items)
            F.append(_f("eligibility_gate", gate, [l1],
                        note=("بوابة أهلية أمامية: منشأة معتمدة (EU 2017/625) قبل "
                              "أي بند لاحق" if gate else
                              "لا بوابة أهلية أمامية مسجّلة لهذا السوق/الفصل")))
        else:
            gaps.append("requirements_checklist: "
                        + (rep.summary or "مرجع L1 بلا بنود لهذا السوق"))
        from silk_tariffs_agent import TariffsAgent
        trep = TariffsAgent().run({"hs_code": hs, "iso3": iso3, "year": year})
        tdp = next((f for f in trep.findings if f.value is not None), None)
        if tdp:
            F.append(_f("tariff_applied_pct", tdp.value, [_dp_src(tdp)], unit="%",
                        note=tdp.note))
        else:
            why = trep.findings[0].note if trep.findings else trep.summary
            gaps.append(f"tariff_applied_pct: {why}")
        return F, gaps


# ── ٤) وكيل التسعير · pricing (طبقتان: حدودية + تجزئة) ──────────────────────

class PricingAgent(ResearchAgent):
    """الطبقة ١: قيم وحدة حدودية = قيمة÷وزن كومتريد (مشتق معلن من رصدين).
    الطبقة ٢: تجزئة مهيكلة عبر /deepen فقط (SerpApi — حارس بنيوي) + مراجع
    أسعار حرة بروابط بلا استخراج أرقام آلي — لا سعر مخترع أبداً."""

    AGENT = "pricing"
    EXPECTED = ("border_unit_value_usd_kg", "saudi_border_unit_value_usd_kg",
                "retail_prices", "margin_at_border_pct", "retail_references")

    def _research(self, task):
        F: list[dict] = []
        gaps: list[str] = []
        hs, iso3, year = task["hs6"], task["iso3"], int(task["year"])
        product, market = task.get("product", ""), task.get("market_name", iso3)

        # الطبقة ١ — حدودية: من المخزن أولاً، وإلا نداء كومتريد واحد (partner=0).
        uv = _border_unit_value(hs, iso3, year)
        uv_src = _src("UN Comtrade (مخزن الحقائق)")
        if uv is None:
            from silk_data_layer import comtrade_trade, primary_value
            recs = comtrade_trade(hs, task.get("m49"), year,
                                  flow="M", partner=0) or []
            rec = next((r for r in recs
                        if primary_value(r) and (r.get("netWgt") or 0) > 0), None)
            if rec:
                uv = primary_value(rec) / float(rec["netWgt"])
                uv_src = _src("UN Comtrade")
        if uv is not None:
            F.append(_f("border_unit_value_usd_kg", round(uv, 2), [uv_src],
                        unit="USD/kg", modeled=True,
                        formula="قيمة الوحدة = قيمة الواردات ÷ الوزن الصافي "
                                "(كلاهما مرصود من كومتريد)",
                        note=f"متوسط سعر الحدود لواردات HS{hs} إلى {iso3} {year}"))
        else:
            gaps.append("border_unit_value_usd_kg: يتطلب قيمة ووزناً صافياً معاً "
                        "من كومتريد — غير متوافرَين لهذه السنة/السوق")
        # قيمة الوحدة السعودية مثلَّثة (إحصاءات المرآة): تقرير الجهة المستوردة
        # (المخزن، صف الشريك SAU) مقابل التقرير السعودي المباشر (reporter=SAU،
        # مرآة) — لا اختلاق، القيمة المعروضة أساسية دوماً والاتفاق/التباين
        # معلن بمصدرين معاً (§4b توسعة).
        sau_uv = None
        try:
            import silk_store
            row = silk_store.get_trade_flow(hs, iso3, "SAU", year)
            if row and row.get("value_usd") and row.get("qty_kg"):
                sau_uv = row["value_usd"] / row["qty_kg"]
        except Exception:  # noqa: BLE001
            pass
        target_dp = (DataPoint(round(sau_uv, 2), "UN Comtrade (مخزن الحقائق)",
                               0.85, "قيمة وحدة الصادر السعودي (تقرير الجهة "
                               "المستوردة، صف الشريك SAU)", _today())
                    if sau_uv is not None else None)
        from silk_data_layer_v2 import mirror_saudi_export
        mirror_raw = mirror_saudi_export(hs, task.get("m49"), iso3, year)
        mv, mq = ((mirror_raw.value or {}).get("value_usd"),
                 (mirror_raw.value or {}).get("qty_kg"))
        mirror_uv = round(mv / mq, 2) if (mv and mq) else None
        mirror_dp = _mirror_dp_for(mirror_raw, mirror_uv)
        tri = _triangulate(target_dp, mirror_dp)
        if tri["value"] is not None:
            F.append(_f("saudi_border_unit_value_usd_kg", tri["value"],
                        tri["sources"], unit="USD/kg", modeled=True,
                        formula="قيمة وحدة الصادر السعودي = قيمة ÷ وزن صافٍ "
                                "(تقرير الجهة المستوردة أو التقرير السعودي "
                                "المباشر — مرآة)", note=tri["note"]))
        else:
            gaps.append("saudi_border_unit_value_usd_kg: لا صف سعودي بوزن "
                        "صافٍ في المخزن ولا في التقرير السعودي المباشر (رصد "
                        "غياب مزدوج، ليس تقديراً)")

        # الطبقة ٢ — تجزئة: مهيكلة مدفوعة (/deepen) أولاً، وإلا Google Shopping
        # المجاني عبر Serper (أي منصة تفهرسها Google لكل دولة `gl` — طلب مالك
        # مباشر: "اي سعر في اي منصة حسب كل دولة") قبل إعلان الفجوة نهائياً.
        from silk_localprice_agent import LocalPriceAgent
        lrep = LocalPriceAgent().run({"query": f"{product} {market}".strip(),
                                      "market": task.get("iso2")})
        listings = [f for f in lrep.findings if f.value is not None]
        if listings:
            F.append(_f("retail_prices",
                        [f.value for f in listings],
                        [_dp_src(f) for f in listings],
                        note=f"{len(listings)} سعر تجزئة مهيكل مؤرّخ (طبقة /deepen)"))
        else:
            paid_why = lrep.findings[0].note if lrep.findings else lrep.summary
            from silk_websearch_agent import web_search_shopping
            shop_raw = web_search_shopping(f"{product} price",
                                           gl=task.get("iso2"))
            shop = [d for d in shop_raw if d.value is not None]
            if shop:
                F.append(_f("retail_prices",
                            [d.value for d in shop],
                            [_src(d.source, d.confidence, url=d.value.get("link"),
                                 retrieved_at=d.retrieved_at) for d in shop],
                            note=f"{len(shop)} سعر تجزئة مرصود من فهرس Google "
                                 "Shopping (أي منصة، عبر Serper) — لا استخراج "
                                 "نصي حر، السعر من حقل منظَّم"))
            else:
                shop_why = shop_raw[0].note if shop_raw else "no shopping results"
                gaps.append(f"retail_prices: {paid_why}؛ ولا نتائج Google "
                            f"Shopping مرصودة ({shop_why})")

        # مراجع أسعار — الطبقة ٣ تستخرج الأسعارَ المذكورةَ صراحةً في العناوين
        # (بلاغ المالك «ترسل روابط»)؛ بلا مفتاح تبقى روابطَ مؤرّخةً للمراجعة.
        from silk_websearch_agent import web_search
        refs = [dp for dp in web_search(f"{product} retail price in {market}", 4)
                if dp.value]
        if refs:
            points = None
            try:
                import silk_ai_judge as aij
                if aij.available():
                    points = aij.extract_prices([d.value for d in refs],
                                                product, market)
            except Exception as e:  # noqa: BLE001 — الاستخلاص اختياري
                log.warning("price extraction skipped: %s", e)
                points = None
            if points:
                F.append(_f("retail_price_points", points,
                            [_src("Web Search → Claude", 0.4)],
                            note="أسعارٌ مذكورةٌ صراحةً في عناوين الويب واستخلصها "
                                 "كلود — مؤشِّرٌ لا سعرَ رفٍّ مؤكَّد (ذاك في /deepen)"))
            F.append(_f("retail_references",
                        [{"title": d.value.get("title", ""),
                          "url": d.value.get("link", ""),
                          "retrieved_at": d.retrieved_at} for d in refs[:3]],
                        [_src("Web Search (Serper)", 0.3,
                              url=d.value.get("link"),
                              retrieved_at=d.retrieved_at) for d in refs[:3]],
                        note=("مصادرُ الاستخلاص — للاستشهاد" if points
                              else "مراجع سعرية للمراجعة اليدوية — لا استخراج أرقام "
                                   "آلي (مفتاح كلود غائب)")))
        else:
            gaps.append("retail_references: بحث الويب غير متاح "
                        "(SEARCH_API_KEY / الشبكة)")

        # هامش عند الحدود — نموذج معلن، يتطلب بطاقة منتج بوحدة kg + قيمة حدودية.
        card = task.get("product_card") or {}
        cost, ship = card.get("cost_per_unit"), card.get("shipping_per_unit") or 0
        if uv is not None and cost and str(card.get("unit", "")).lower() == "kg":
            margin = round(100 * (uv - float(cost) - float(ship)) / uv, 1)
            F.append(_f("margin_at_border_pct", margin, [uv_src], unit="%",
                        modeled=True,
                        formula=f"الهامش = (قيمة الوحدة الحدودية {uv:.2f} − "
                                f"تكلفتك {cost} − شحن {ship}) ÷ قيمة الوحدة",
                        note="مُقدَّر عند متوسط سعر الحدود — ليس سعر بيع تجزئة"))
        else:
            gaps.append("margin_at_border_pct: يتطلب بطاقة منتج بوحدة kg "
                        "(cost_per_unit) + قيمة وحدة حدودية مرصودة")
        return F, gaps


# ── ٥) وكيل المخاطر · risk ───────────────────────────────────────────────────

class RiskAgent(ResearchAgent):
    """WGI (استقرار/تنظيم) + LPI لوجستي + تقلب صرف من السلسلة + تركّز مورّدين."""

    AGENT = "risk"
    PREF_KEY = "risk"
    EXPECTED = ("political_stability_wgi", "regulatory_quality_wgi",
                "logistics_lpi", "fx_volatility_pct", "supplier_concentration_hhi")

    _INDICATORS = (("PV.EST", "political_stability_wgi", "الاستقرار السياسي (WGI)"),
                   ("RQ.EST", "regulatory_quality_wgi", "جودة التنظيم (WGI)"),
                   ("LP.LPI.OVRL.XQ", "logistics_lpi", "الأداء اللوجستي (LPI)"))

    def _research(self, task):
        F: list[dict] = []
        gaps: list[str] = []
        iso3, year = task["iso3"], int(task["year"])
        import silk_store
        for ind, metric, label in self._INDICATORS:
            got = None
            try:
                got = silk_store.get_indicator(iso3, ind)
            except Exception:  # noqa: BLE001 — المخزن تحسين لا شرط
                got = None
            if got and got.get("value") is not None:
                F.append(_f(metric, round(float(got["value"]), 3),
                            [_src(got.get("source", "World Bank"),
                                  float(got.get("confidence") or 0.9))],
                            note=f"{label} — {ind} سنة {got.get('year')} "
                                 "(مخزن الحقائق)"))
            else:
                from silk_data_layer import world_bank
                dp = world_bank(iso3, ind)
                if dp.value is not None:
                    F.append(_f(metric, dp.value, [_dp_src(dp)],
                                note=f"{label} — {dp.note}"))
                else:
                    gaps.append(f"{metric}: {label} غير متاح (مخزن بارد + "
                                f"{dp.note})")
        try:
            series = silk_store.get_indicator_series(iso3, "PA.NUS.FCRF")
        except Exception:  # noqa: BLE001
            series = []
        vals = [r["value"] for r in series if r.get("value")]
        if len(vals) >= 3:
            mean = sum(vals) / len(vals)
            cov = round(100 * (sum((v - mean) ** 2 for v in vals)
                               / len(vals)) ** 0.5 / mean, 2) if mean else None
            F.append(_f("fx_volatility_pct", cov,
                        [_src(series[-1].get("source", "World Bank"), 0.85)],
                        unit="%", modeled=True,
                        formula=f"معامل الاختلاف = انحراف معياري ÷ متوسط × 100 "
                                f"على {len(vals)} سنوات PA.NUS.FCRF",
                        note="تقلب سعر الصرف من السلسلة المخزّنة"))
        else:
            gaps.append("fx_volatility_pct: يتطلب سلسلة PA.NUS.FCRF (٣+ سنوات) — "
                        "شغّل جامع worldbank (tools/refresh.py)")
        # تركّز المورّدين — نفس HHI من صفوف المخزن (رخيص، محلي).
        try:
            got = silk_store.market_imports_from_store(task["hs6"], iso3, year)
            partners = got["partners"]
        except Exception:  # noqa: BLE001
            partners = []
        if partners:
            grand = sum(p["value_usd"] for p in partners)
            hhi = round(sum((p["value_usd"] / grand) ** 2 for p in partners), 3)
            F.append(_f("supplier_concentration_hhi", hhi, [_src("UN Comtrade")],
                        note="تركّز مصادر التوريد للسوق — >0.25 اعتماد مركّز "
                             "(خطر انقطاع/حرب أسعار)"))
        else:
            gaps.append("supplier_concentration_hhi: لا صفوف شركاء في المخزن")
        # بوابة الخطر الحرج — قاعدة معلنة على رصد WGI.
        pv = next((f["value"] for f in F
                   if f["metric"] == "political_stability_wgi"), None)
        if pv is not None:
            F.append(_f("critical_risk", bool(pv < -1.5),
                        [_src("World Bank", 0.9)], modeled=True,
                        formula="قاعدة: PV.EST < −1.5 ⇒ خطر سياسي حرج "
                                "(بوابة محرك القرار)",
                        note="علم بوابة الخطر الحرج — مشتق بقاعدة معلنة"))
        return F, gaps


# ── ٦) وكيل المستهلك والطلب · consumer & demand ─────────────────────────────

_muslim_cache: dict | None = None


def muslim_share(iso3: str) -> dict | None:
    """حصة مسلمة من المرجع الساكن المُستشهَد — cited static snapshot or None."""
    global _muslim_cache
    if _muslim_cache is None:
        _muslim_cache = {}
        try:
            with open(os.path.join(_DATA_DIR, "muslim_share.csv"),
                      encoding="utf-8") as fh:
                rows = [r for r in fh if not r.startswith("#")]
            for r in csv.DictReader(rows):
                _muslim_cache[r["iso3"].strip().upper()] = {
                    "pct": float(r["muslim_share_pct"]),
                    "ref_year": r["ref_year"], "note": r.get("note", "")}
        except Exception as e:  # noqa: BLE001 — مرجع غائب = فجوة، لا انهيار
            log.warning("muslim_share reference unavailable: %s", e)
    return _muslim_cache.get((iso3 or "").upper())


_PEW_SRC = dict(source="Pew Research Center (لقطة ساكنة مقرّبة)", confidence=0.7,
                url="https://www.pewresearch.org/religion/feature/"
                    "religious-composition-by-country-2010-2050/")


class ConsumerDemandAgent(ResearchAgent):
    """دخل وسكان (مخزن→حي) + استهلاك فردي (FAOSTAT) + اهتمام بحث (Trends) +
    حصة مسلمة (مرجع Pew ساكن) وموسمية رمضان كقاعدة معلنة عليها."""

    AGENT = "consumer_demand"
    PREF_KEY = "consumer"
    EXPECTED = ("gdp_per_capita_usd", "population", "percapita_supply_kg",
                "search_interest", "muslim_share_pct", "ramadan_seasonality")

    def _research(self, task):
        F: list[dict] = []
        gaps: list[str] = []
        iso3 = task["iso3"]
        import silk_store
        for ind, metric, label in (("NY.GDP.PCAP.CD", "gdp_per_capita_usd",
                                    "نصيب الفرد من الناتج ($)"),
                                   ("SP.POP.TOTL", "population", "السكان")):
            got = None
            try:
                got = silk_store.get_indicator(iso3, ind)
            except Exception:  # noqa: BLE001
                got = None
            if got and got.get("value") is not None:
                F.append(_f(metric, got["value"],
                            [_src(got.get("source", "World Bank"),
                                  float(got.get("confidence") or 0.9))],
                            note=f"{label} — سنة {got.get('year')} (مخزن الحقائق)"))
            else:
                from silk_data_layer import world_bank
                dp = world_bank(iso3, ind)
                if dp.value is not None:
                    F.append(_f(metric, dp.value, [_dp_src(dp)], note=dp.note))
                else:
                    gaps.append(f"{metric}: {dp.note}")
        from silk_faostat_agent import FaostatAgent
        frep = FaostatAgent().run({"iso3": iso3, "item": task.get("product"),
                                   "year": task.get("year")})
        fdp = next((f for f in frep.findings if f.value is not None), None)
        if fdp:
            F.append(_f("percapita_supply_kg", fdp.value, [_dp_src(fdp)],
                        unit="kg/capita/yr", note=fdp.note))
        else:
            why = frep.findings[0].note if frep.findings else frep.summary
            gaps.append(f"percapita_supply_kg: {why}")
        from silk_trends_agent import TrendsAgent
        trep = TrendsAgent().run({"keyword": task.get("product"),
                                  "geo": task.get("iso2")})
        tdp = next((f for f in trep.findings if f.value is not None), None)
        if tdp:
            F.append(_f("search_interest", tdp.value, [_dp_src(tdp)],
                        note=tdp.note))
        else:
            why = trep.findings[0].note if trep.findings else trep.summary
            gaps.append(f"search_interest: {why}")
        ms = muslim_share(iso3)
        if ms:
            F.append(_f("muslim_share_pct", ms["pct"], [dict(_PEW_SRC)], unit="%",
                        note=f"لقطة ساكنة مقرّبة (إسقاطات {ms['ref_year']}) — "
                             f"{ms['note']}؛ للقراءة التجارية لا الإحصاء الرسمي"))
            likely = ms["pct"] >= 25
            F.append(_f("ramadan_seasonality",
                        "موسمية رمضان/العيدين مرجّحة تجارياً" if likely
                        else "أثر موسمية رمضان محدود متوقّعاً",
                        [dict(_PEW_SRC)], modeled=True,
                        formula="قاعدة معلنة: حصة مسلمة ≥ 25% ⇒ موسمية رمضان/"
                                "العيدين ذات أثر تجاري",
                        note="استنتاج قاعدي من الحصة المرصودة أعلاه — ليس رصد "
                             "مبيعات موسمية"))
        else:
            gaps.append(f"muslim_share_pct: {iso3} خارج المرجع الساكن — "
                        "أضف صفاً مُستشهَداً في data/muslim_share.csv")
            gaps.append("ramadan_seasonality: يتطلب حصة مسلمة مرصودة")
        return F, gaps


# ── ٧) وكيل المورّدين والمصنّعين · supplier & manufacturer ───────────────────

class SupplierAgent(ResearchAgent):
    """دليل مورّدين: سعوديون (جانب المنشأ) + موزّعون في السوق المستهدف —
    مرشّحون بالاسم برابط وتاريخ، غير موثَّقين (0.4)، لا أسماء مخترعة أبداً."""

    AGENT = "supplier"
    PREF_KEY = "maps"
    EXPECTED = ("saudi_suppliers", "target_distributors")

    def _research(self, task):
        F: list[dict] = []
        gaps: list[str] = []
        product = task.get("product", "")
        market = task.get("market_name", task.get("iso3", ""))
        sa, sa_refs, sa_drop = _entities_and_references(
            [f"{product} manufacturers suppliers Saudi Arabia",
             f"مصانع موردي {product} السعودية"],
            f"{product} مصنع مورد السعودية", region="sa",
            product=product, market="السعودية",
            role="مصنّع أو مورّد بالجملة")
        if sa:
            F.append(_f("saudi_suppliers", sa, sa_refs,
                        note="مرشّحو توريد سعوديون (جانب المنشأ) — غير موثَّقين، "
                             "أكّدهم قبل التعاقد"
                             + (f" · استُبعد {sa_drop} محل تجزئة/مطعم" if sa_drop else "")))
        else:
            gaps.append("saudi_suppliers: "
                        + (f"استُبعدت {sa_drop} نتيجة تجزئة/مطعم — لا مورّد/مصنع "
                           "بالجملة مؤكّد عبر البحث المجاني. " if sa_drop else "")
                        + "يتطلب SEARCH_API_KEY / GOOGLE_MAPS_API_KEY — لا أسماء مخترعة")
        tg, tg_refs, tg_drop = _entities_and_references(
            [f"{product} importers wholesale distributors in {market}"],
            f"{product} wholesale distributor {market}",
            product=product, market=market,
            role="موزّع أو مستورد بالجملة")
        if tg:
            F.append(_f("target_distributors", tg, tg_refs,
                        note=f"مرشّحو توزيع في {market} — غير موثَّقين؛ الترقية "
                             "الموثّقة عبر /deepen"
                             + (f" · استُبعد {tg_drop} محل تجزئة/مطعم" if tg_drop else "")))
        else:
            gaps.append("target_distributors: "
                        + (f"استُبعدت {tg_drop} نتيجة تجزئة/مطعم غير ذات صلة — لا "
                           "موزّع بالجملة مؤكّد عبر البحث المجاني؛ المستوردون "
                           "الموثّقون من السجلّات الجمركية عبر Volza/Explee (/deepen). "
                           if tg_drop else "")
                        + "يتطلب SEARCH_API_KEY / GOOGLE_MAPS_API_KEY — لا أسماء مخترعة")
        return F, gaps


# ── ٨) وكيل اللوجستيات · logistics (زمن التوريد + جسر التكلفة حتى الوصول) ─────

class LogisticsAgent(ResearchAgent):
    """زمن التوريد والأداء اللوجستي من البنك الدولي (LPI + زمن عبور الحدود) —
    والتكلفة حتى الوصول (الشحن) جسرٌ صريحٌ للطبقة المدفوعة، لا رقمٌ مخترَع.

    توجيه المالك: وكيلٌ ثامنٌ يسدّ فجوة اللوجستيات (زمن التوريد + التكلفة حتى
    الوصول). المجاني الصادق يرصد: توقيت التسليم وسهولة ترتيب الشحن (LPI) وزمن
    امتثال الحدود؛ أمّا سعر الشحن الفعلي $/كغ فيتطلب سجلاتِ شحنٍ حقيقية (Volza)
    — فيُعلَن فجوةً موجَّهةً للتعميق المدفوع لا يُقدَّر بلا مصدر (المبدأ التأسيسي).
    """

    AGENT = "logistics"
    EXPECTED = ("lead_time_days", "lpi_timeliness", "lpi_intl_shipments",
                "freight_cost_usd_kg", "landed_cost_usd_kg")

    _INDICATORS = (("LP.LPI.TIME.XQ", "lpi_timeliness",
                    "توقيت وصول الشحنات (LPI)"),
                   ("LP.LPI.ITRN.XQ", "lpi_intl_shipments",
                    "سهولة ترتيب شحنات دولية تنافسية (LPI)"))

    def _research(self, task):
        F: list[dict] = []
        gaps: list[str] = []
        iso3 = task["iso3"]
        import silk_store
        from silk_data_layer import world_bank
        for ind, metric, label in self._INDICATORS:
            got = None
            try:
                got = silk_store.get_indicator(iso3, ind)
            except Exception:  # noqa: BLE001 — المخزن تحسين لا شرط
                got = None
            if got and got.get("value") is not None:
                F.append(_f(metric, round(float(got["value"]), 3),
                            [_src(got.get("source", "World Bank"),
                                  float(got.get("confidence") or 0.9))],
                            note=f"{label} — {ind} سنة {got.get('year')} "
                                 "(مخزن الحقائق)"))
            else:
                dp = world_bank(iso3, ind)
                if dp.value is not None:
                    F.append(_f(metric, dp.value, [_dp_src(dp)],
                                note=f"{label} — {dp.note}"))
                else:
                    gaps.append(f"{metric}: {label} غير متاح (مخزن بارد + "
                                f"{dp.note})")
        # زمن التوريد — زمن امتثال الحدود للاستيراد (ساعات → أيام)، من قاعدة
        # مؤشرات ممارسة الأعمال؛ غيابه فجوةٌ معلنة لا تقدير.
        hours = None
        try:
            got = silk_store.get_indicator(iso3, "IC.IMP.TMBC")
            hours = got.get("value") if got else None
        except Exception:  # noqa: BLE001
            hours = None
        if hours is None:
            dp = world_bank(iso3, "IC.IMP.TMBC")
            hours = dp.value
            src = _dp_src(dp) if dp.value is not None else None
        else:
            src = _src("World Bank", 0.85)
        if hours is not None:
            F.append(_f("lead_time_days", round(float(hours) / 24, 1), [src],
                        unit="يوم", modeled=True,
                        formula="زمن امتثال الحدود للاستيراد (IC.IMP.TMBC، ساعات) ÷ 24",
                        note="زمن التخليص الحدودي فقط — لا يشمل زمن الشحن البحري/"
                             "الجوي (ذاك في الطبقة المدفوعة مع مسار الشحن)"))
        else:
            gaps.append("lead_time_days: زمن امتثال الحدود (IC.IMP.TMBC) غير "
                        "متاح — شغّل جامع worldbank (tools/refresh.py)")
        # سعر الشحن الفعلي والتكلفة حتى الوصول — جسرٌ صريحٌ للطبقة المدفوعة.
        gaps.append("freight_cost_usd_kg: سعر الشحن الفعلي $/كغ يتطلب سجلاتِ "
                    "شحنٍ حقيقية (Volza/Explee عبر /deepen) — لا يُقدَّر بلا مصدر")
        gaps.append("landed_cost_usd_kg: التكلفة حتى الوصول = سعر الحدود + الشحن؛ "
                    "تُحسب بعد رصد الشحن (الطبقة المدفوعة) وبطاقة المنتج")
        return F, gaps


# ── المنسّق · orchestrator ───────────────────────────────────────────────────

ALL_AGENTS: tuple[type[ResearchAgent], ...] = (
    MarketSizeAgent, CompetitorAgent, RegulatoryAgent, PricingAgent,
    RiskAgent, ConsumerDemandAgent, SupplierAgent, LogisticsAgent)


class ResearchOrchestrator:
    """يوزّع الوكلاء الثمانية بالتوازي بمهلة، يتحقق، يجمّع، ويسجّل التشغيلات.

    فشل وكيل (خطأ/مهلة/مخطط) = مغلف failed بسببه الظاهر — لا يحجب البقية ولا
    التقرير (§4b «فشل غير محاجز وصادق»). التغطية الكلية = متوسط تغطيات الوكلاء
    (أوزان محرك القرار تأتي في Stage 4).
    """

    def __init__(self, timeout: float | None = None,
                 agent_classes=None) -> None:
        self.timeout = timeout or DEFAULT_TIMEOUT
        self.agents = [c() for c in (agent_classes or ALL_AGENTS)]

    def run_market(self, task: dict) -> dict:
        outputs: dict[str, dict] = {}
        with _cf.ThreadPoolExecutor(max_workers=len(self.agents)) as ex:
            futs = {ex.submit(a.run, dict(task)): a for a in self.agents}
            deadline = _time.monotonic() + self.timeout
            for fut, a in futs.items():
                try:
                    rep = fut.result(
                        timeout=max(0.05, deadline - _time.monotonic()))
                    outputs[a.AGENT] = self._envelope(rep, a, task)
                except _cf.TimeoutError:
                    fut.cancel()
                    outputs[a.AGENT] = _failed_output(
                        a.AGENT, task,
                        f"timeout: تجاوز الوكيل مهلة {self.timeout}s — فشل "
                        "معلن غير محاجز، بقية الوكلاء لم تتأثر")
                except Exception as e:  # noqa: BLE001 — لا يسقط سوق كامل بوكيل
                    outputs[a.AGENT] = _failed_output(
                        a.AGENT, task, f"{type(e).__name__}: {e}")
        coverage = round(sum(o["coverage"] for o in outputs.values())
                         / max(1, len(outputs)), 2)
        self._record_runs(outputs)
        return {"schema": SCHEMA, "agents": outputs, "coverage": coverage,
                "pillar_inputs": _pillar_inputs(outputs),
                "note": "حزمة وكلاء البحث الثمانية — كل رقم بمصدره؛ فشل وكيل "
                        "يظهر بسببه ولا يحجب البقية"}

    @staticmethod
    def _envelope(rep: AgentReport, agent: ResearchAgent, task: dict) -> dict:
        if (rep.findings and isinstance(rep.findings[0], dict)
                and rep.findings[0].get("agent")):
            return rep.findings[0]
        # مسار حارس BaseAgent (استثناء غير متوقع): DataPoint واحد بملاحظة السبب.
        note = rep.summary or (getattr(rep.findings[0], "note", "")
                               if rep.findings else "فشل غير مفسَّر")
        return _failed_output(agent.AGENT, task, note)

    @staticmethod
    def _record_runs(outputs: dict[str, dict]) -> None:
        try:
            import silk_store
            silk_store.migrate()
            for o in outputs.values():
                silk_store.record_agent_run(
                    o["agent"], o.get("hs6", ""), o.get("iso3", ""),
                    o["status"], o["coverage"], o.get("started_at", ""),
                    o.get("finished_at", ""),
                    note="; ".join(o.get("gaps", [])[:3]))
        except Exception as e:  # noqa: BLE001 — السجل تحسين لا شرط
            log.warning("agent_runs recording skipped: %s", e)


def _metric_value(outputs: dict, agent: str, metric: str):
    for f in (outputs.get(agent) or {}).get("findings", []):
        if f.get("metric") == metric and f.get("value") is not None:
            return f["value"]
    return None


def _pillar_inputs(outputs: dict) -> dict:
    """مدخلات الأعمدة الخام لمحرك القرار (Stage 4) — قيم مرصودة أو None، لا تعويض."""
    mv = lambda a, m: _metric_value(outputs, a, m)  # noqa: E731 — اختصار موضعي
    named = mv("competitor", "named_companies") or []
    return {
        "market_attractiveness": {
            "tam_usd": mv("market_size", "tam_usd"),
            "import_cagr_pct": mv("market_size", "import_cagr_pct"),
            "gdp_per_capita_usd": mv("consumer_demand", "gdp_per_capita_usd"),
            "saudi_share_pct": mv("competitor", "saudi_share_pct"),
            # المرحلة ٢ (§7): بديل جزئي غير دولاري عند غياب TAM الرسمي —
            # يُستهلَك في _pillar_market فقط عندما يكون tam_log نفسه غائباً.
            "market_activity_index": mv("market_size", "market_activity_index")},
        "competition_intensity": {
            "hhi": mv("competitor", "hhi"),
            "top_supplier_share_pct": mv("competitor", "top_supplier_share_pct"),
            "named_company_count": len(named) if named else None},
        "regulatory_fit": {
            "tariff_applied_pct": mv("regulatory", "tariff_applied_pct"),
            "entry_requirements_count": mv("regulatory",
                                           "entry_requirements_count"),
            "eligibility_gate": mv("regulatory", "eligibility_gate")},
        "profitability": {
            "border_unit_value_usd_kg": mv("pricing", "border_unit_value_usd_kg"),
            "saudi_border_unit_value_usd_kg":
                mv("pricing", "saudi_border_unit_value_usd_kg"),
            "margin_at_border_pct": mv("pricing", "margin_at_border_pct")},
        "risk": {
            "political_stability_wgi": mv("risk", "political_stability_wgi"),
            # توجيه المالك: المخاطر عمودٌ موزون — يحتاج جودةَ التنظيم والأداءَ
            # اللوجستي (ينتجهما وكيل risk) لا الاستقرارَ والصرفَ فقط.
            "regulatory_quality_wgi": mv("risk", "regulatory_quality_wgi"),
            "logistics_lpi": mv("risk", "logistics_lpi"),
            "fx_volatility_pct": mv("risk", "fx_volatility_pct"),
            "supplier_concentration_hhi": mv("risk",
                                             "supplier_concentration_hhi"),
            "critical_risk": mv("risk", "critical_risk")},
        # وكيل اللوجستيات (الثامن): زمن التوريد + جسر التكلفة حتى الوصول (مدفوع)
        "logistics": {
            "lead_time_days": mv("logistics", "lead_time_days"),
            "lpi_timeliness": mv("logistics", "lpi_timeliness"),
            "lpi_intl_shipments": mv("logistics", "lpi_intl_shipments"),
            "freight_cost_usd_kg": mv("logistics", "freight_cost_usd_kg"),
            "landed_cost_usd_kg": mv("logistics", "landed_cost_usd_kg")},
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Silk research orchestrator — ثمانية وكلاء، فشل معلن لا صامت "
          "(offline => فجوات موسومة، لا اختلاق)\n")
    bundle = ResearchOrchestrator(timeout=30).run_market(
        {"product": "تمور", "hs6": "080410", "iso3": "CHN", "m49": "156",
         "iso2": "CN", "market_name": "China", "year": 2023})
    for name, out in bundle["agents"].items():
        print(f"  [{out['status']:^8}] {name}: coverage={out['coverage']} "
              f"findings={sum(1 for f in out['findings'] if f['value'] is not None)} "
              f"gaps={len(out['gaps'])}")
    print(f"\n  التغطية الكلية: {bundle['coverage']}")
