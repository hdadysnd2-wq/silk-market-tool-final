"""محرّك ترتيب الأسواق لسِلك — Silk market ranking engine.

Compares several target markets for ONE HS code and ranks them by a transparent,
weighted score. Every component carries its DataPoint provenance so a human can
audit the ranking. Real public data only (Comtrade + World Bank via the data
layer). Missing component => skipped + lowered row confidence; never fabricated.
"""
from __future__ import annotations

import datetime
import logging
import os
from concurrent.futures import ThreadPoolExecutor

from silk_data_layer import (
    DataPoint,
    gdp_per_capita,
    population,
    _today,
)
from silk_data_layer_v2 import market_imports_cached, ppp_per_capita, market_imports

log = logging.getLogger(__name__)


def _dyear(year: object) -> "int | None":
    """سنة البيانات كعددٍ للحقل البنيويّ data_year (الدرس ٣٣) — None عند التعذّر."""
    try:
        return int(str(year)[:4])
    except (TypeError, ValueError):
        return None


_SAUDI_M49 = "682"

# أسواق سِلك المستهدفة — Silk target markets (iso3 + M49). Real codes; GCC,
# wider MENA, key African, Asian and European import markets.
COUNTRIES: list[dict] = [
    # GCC
    {"iso3": "ARE", "m49": "784"}, {"iso3": "QAT", "m49": "634"},
    {"iso3": "KWT", "m49": "414"}, {"iso3": "OMN", "m49": "512"},
    {"iso3": "BHR", "m49": "048"},
    # wider MENA
    {"iso3": "JOR", "m49": "400"}, {"iso3": "LBN", "m49": "422"},
    {"iso3": "EGY", "m49": "818"}, {"iso3": "MAR", "m49": "504"},
    {"iso3": "TUN", "m49": "788"}, {"iso3": "DZA", "m49": "012"},
    {"iso3": "IRQ", "m49": "368"}, {"iso3": "TUR", "m49": "792"},
    {"iso3": "YEM", "m49": "887"},
    # Africa
    {"iso3": "ZAF", "m49": "710"}, {"iso3": "NGA", "m49": "566"},
    {"iso3": "KEN", "m49": "404"}, {"iso3": "ETH", "m49": "231"},
    {"iso3": "GHA", "m49": "288"},
    # Asia
    {"iso3": "IND", "m49": "356"}, {"iso3": "PAK", "m49": "586"},
    {"iso3": "BGD", "m49": "050"}, {"iso3": "IDN", "m49": "360"},
    {"iso3": "MYS", "m49": "458"}, {"iso3": "SGP", "m49": "702"},
    {"iso3": "THA", "m49": "764"}, {"iso3": "VNM", "m49": "704"},
    {"iso3": "CHN", "m49": "156"}, {"iso3": "JPN", "m49": "392"},
    {"iso3": "KOR", "m49": "410"},
    # Europe / North America
    {"iso3": "GBR", "m49": "826"}, {"iso3": "DEU", "m49": "276"},
    {"iso3": "FRA", "m49": "250"}, {"iso3": "ITA", "m49": "380"},
    {"iso3": "ESP", "m49": "724"}, {"iso3": "NLD", "m49": "528"},
    {"iso3": "USA", "m49": "840"}, {"iso3": "CAN", "m49": "124"},
]

# ISO3 → ISO2 لأسواق سِلك — كان غائباً من طبقة بايثون كلياً (موجوداً في JS
# الواجهة فقط)، فكل صف مرتَّب خرج بلا iso2: وكيل Trends قاس الاهتمام
# **عالمياً** بدل السوق المستهدف (geo=None تراجع صامت)، وبحث التسوّق في
# طبقة التسعير فقد نطاق الدولة (gl=None). إصلاح P0-3 — تجويع مفاتيح صامت.
ISO2: dict[str, str] = {
    "SAU": "SA", "ARE": "AE", "QAT": "QA", "KWT": "KW", "OMN": "OM",
    "BHR": "BH", "JOR": "JO", "LBN": "LB", "EGY": "EG", "MAR": "MA",
    "TUN": "TN", "DZA": "DZ", "IRQ": "IQ", "TUR": "TR", "YEM": "YE",
    "ZAF": "ZA", "NGA": "NG", "KEN": "KE", "ETH": "ET", "GHA": "GH",
    "IND": "IN", "PAK": "PK", "BGD": "BD", "IDN": "ID", "MYS": "MY",
    "SGP": "SG", "THA": "TH", "VNM": "VN", "CHN": "CN", "JPN": "JP",
    "KOR": "KR", "GBR": "GB", "DEU": "DE", "FRA": "FR", "ITA": "IT",
    "ESP": "ES", "NLD": "NL", "USA": "US", "CAN": "CA",
}

def world_import_totals(hs_code: str, year: int) -> list[dict]:
    """كل مستوردي هذا الرمز عالمياً بقيمهم — every world importer of this HS, ONE call.

    نداءٌ واحدٌ فقط (كل الدول المبلّغة، partner=0=العالم، flow=M) يُعدِّد **كل**
    سوقٍ في العالم مع إجمالي وارداته، مرتَّباً تنازلياً بالقيمة. هذا هو نفس
    النداء الذي كان `top_import_markets` يجريه — لكنه الآن يُعيد القيمة أيضاً كي
    تُشتَقّ منه علامةُ «حجم السوق» لصفوف الفئة-٢ (تغطية العالم) **بلا أيّ نداءٍ
    إضافيٍّ لكل دولة**. صفٌّ بلا قيمة رقمية يُسقط؛ رمز m49 بلا ترجمة iso3 يُسقط
    مع تسجيل (تدهور معلن). فشل كومتريد/غياب الشبكة => [] والمستدعي يتراجع.

    ONE Comtrade call enumerating every reporting country with its import total —
    the shared source both for Tier-1 dynamic candidates AND for Tier-2 market
    size (zero extra per-country calls). Returns [{iso3, m49, total_usd}] desc.
    """
    from silk_data_layer import M49_TO_ISO3, comtrade_trade, primary_value
    recs = comtrade_trade(hs_code, None, year, flow="M", partner=0) or []
    rows: list[tuple[float, str, str]] = []
    skipped = 0
    for rec in recs or []:
        m49 = str(rec.get("reporterCode") or "").strip()
        if not m49 or m49 == _SAUDI_M49:      # السعودية منشأ لا سوق مستهدف
            continue
        val = primary_value(rec)
        if val is None:
            continue
        iso3 = (str(rec.get("reporterISO") or "").strip().upper()
                or M49_TO_ISO3.get(m49, ""))
        if len(iso3) != 3:
            skipped += 1
            continue
        rows.append((val, iso3, m49))
    if skipped:
        log.info("world_import_totals: %d reporter(s) skipped — no ISO3 "
                 "mapping (declared degradation)", skipped)
    rows.sort(reverse=True)
    seen: set[str] = set()
    out: list[dict] = []
    for val, iso3, m49 in rows:
        if iso3 in seen:
            continue
        seen.add(iso3)
        out.append({"iso3": iso3, "m49": m49, "total_usd": val})
    return out


def top_import_markets(hs_code: str, year: int, n: int = 38) -> list[dict]:
    """أكبر مستوردي هذا الرمز عالمياً — top-N dynamic candidates (8c).

    قشرةٌ رقيقة فوق `world_import_totals`: نفس النداء الواحد، أول n سوقاً فقط،
    بنفس شكل مخرجات اليوم `{iso3, m49}` حرفياً (بلا انحدار للمستدعين القدامى).
    Thin slice over `world_import_totals` — identical legacy output shape.
    """
    return [{"iso3": t["iso3"], "m49": t["m49"]}
            for t in world_import_totals(hs_code, year)[:n]]


# ═══ استشارة بلد المنشأ (SILK_PRODUCER_ADVISORY) — producer-country advisory ═══
# قاعدةٌ عامّةٌ مبنيّةٌ على البيانات لا حالةَ منتج: قبل حجز دراسةِ دخولِ سوقٍ ما،
# إن كانت تلك السوق من **أكبر مصدّري هذا الرمز عالميًا** (منشأ لا مستورِد) فالدخول
# تنافسيٌّ جدًّا — نُحذّر ونطلب موافقةً صريحة. المصدر: نداءُ عالمٍ واحدٌ بتدفّق
# التصدير (`flow="X"`, partner=0) — نظيرُ نداء الاستيراد تمامًا، صفر نداء كلود/
# سقفٍ مدفوع (كومتريد فقط، مقيسٌ بميزانيته). صفر رمز دولة/HS مكتوب صلبًا هنا.

def world_export_totals(hs_code: str, year: int) -> list[dict]:
    """كل مصدّري هذا الرمز عالميًا بقيمهم — every world EXPORTER of this HS, ONE call.

    نظيرُ `world_import_totals` بتدفّق التصدير (`flow="X"`, كل الدول المبلّغة،
    partner=0=العالم): يُعدِّد كلَّ **بلد منشأ** يُصدِّر هذا الرمز مع إجمالي
    صادراته، مرتَّبًا تنازليًا. يُستعمَل لاستشارة بلد المنشأ (هل السوق المستهدفة
    من أكبر المنتِجين؟). نداءُ كومتريد واحدٌ مُخبّأٌ (cache) — صفر نداء مدفوع
    (كلود/سقف). فشل/غياب الشبكة => [] فتصمت الاستشارة (فشلٌ آمن مفتوح).

    Mirror of `world_import_totals` with the export flow — the world-producers
    ranking by reporter for a given HS. Returns [{iso3, m49, total_usd}] desc.
    """
    from silk_data_layer import M49_TO_ISO3, comtrade_trade, primary_value
    recs = comtrade_trade(hs_code, None, year, flow="X", partner=0) or []
    rows: list[tuple[float, str, str]] = []
    for rec in recs or []:
        m49 = str(rec.get("reporterCode") or "").strip()
        if not m49:
            continue
        val = primary_value(rec)
        if val is None:
            continue
        iso3 = (str(rec.get("reporterISO") or "").strip().upper()
                or M49_TO_ISO3.get(m49, ""))
        if len(iso3) != 3:
            continue
        rows.append((val, iso3, m49))
    rows.sort(reverse=True)
    seen: set[str] = set()
    out: list[dict] = []
    for val, iso3, m49 in rows:
        if iso3 in seen:
            continue
        seen.add(iso3)
        out.append({"iso3": iso3, "m49": m49, "total_usd": val})
    return out


def _producer_advisory_topn() -> int:
    """عتبة «من أكبر المصدّرين» قابلةٌ للضبط بالبيئة فقط — SILK_PRODUCER_ADVISORY_TOPN
    (افتراضيًا ٥). لا رقم مكتوب صلبًا في المنطق العام."""
    try:
        n = int(os.environ.get("SILK_PRODUCER_ADVISORY_TOPN", "5") or "5")
    except ValueError:
        n = 5
    return max(1, n)


def top_world_exporters(hs_code: str, year: int, n: int | None = None) -> list[dict]:
    """أكبر n مصدّرًا عالميًا لهذا الرمز — thin slice over `world_export_totals`."""
    n = _producer_advisory_topn() if n is None else max(1, n)
    return world_export_totals(hs_code, year)[:n]


def is_top_world_exporter(hs_code, iso3: str, year: int,
                          n: int | None = None) -> tuple[bool, list]:
    """هل السوق ضمن أكبر مصدّري هذا الرمز عالميًا؟ — (is_top, top_exporters).

    قاعدةٌ مبنيّةٌ على البيانات: نُرتّب أكبر المصدّرين من نداء العالم الواحد
    (تصدير) ونفحص عضوية `iso3`. تعذّرُ التحديد (بلا رمز/شبكة/كومتريد) =>
    `(False, [])`: **تصمت الاستشارة** بدل تحذيرٍ كاذب (فشلٌ آمن مفتوح، نظير
    `_market_in_coverage`). صفر اسم دولة/HS مكتوب صلبًا — كلّه من البيانات.
    """
    iso3 = (iso3 or "").strip().upper()
    if not hs_code or len(iso3) != 3:
        return False, []
    try:
        top = top_world_exporters(hs_code, year, n)
    except Exception as e:  # noqa: BLE001 — عطل قياس لا يُطلق تحذيرًا كاذبًا
        log.warning("producer advisory probe failed: %s", e)
        return False, []
    return iso3 in {t["iso3"] for t in top}, top


# ═══ البند أ٢ — فحص معقولية بلد المورّد · A2 supplier-country plausibility ═══
# إشارةٌ اقتصاديةٌ مُعاضِدةٌ لتأكيد رمز HS: بوّابات التأكيد القائمة نصّية فقط
# (تداخل صفات المنتج مع وصف الرمز). لا شيء منها يقارن **موردي السوق الفعليين**
# بما يجب أن يبدو عليه ملفُّ مصدّرٍ معقولٍ للرمز — فرمزٌ خاطئٌ لكنه نصّياً معقول
# يعبرها. البند أ٢ يقارن مجموعتين كلتاهما من كومتريد حيّ (صفر نداء مدفوع، صفر
# رمز دولة/HS مكتوب صلبًا): أكبر موردي السوق لهذا الرمز، وأكبر مصدّري الرمز
# عالميًا. تفكّكٌ شبه تامٌّ بينهما = الرمز قد يصف عائلةً مختلفةً عمّا يُتاجَر
# فعلاً تحته (حادثة زبدة الفول السوداني/الألبان: أيرلندا/نيوزيلندا تتصدّران
# 040510 لا مصدّرو زبدة الفول السوداني). المذكّرة: docs/DESIGN_A2_SUPPLIER_PLAUSIBILITY.md.


def _a2_plausibility_enabled() -> bool:
    """صمّام البند أ٢ — `SILK_A2_PLAUSIBILITY=1` يفعّله (افتراضي مُطفأ =>
    السلوك كاليوم). طرحٌ محافظٌ خلف صمّام حتى يعايره المالك حيًّا."""
    return os.environ.get("SILK_A2_PLAUSIBILITY", "0").strip() == "1"


def _a2_params() -> tuple[int, int, float]:
    """عتبات البند أ٢ config-driven (لا رقم صلب في المنطق):
    (أعلى M موردٍ للسوق، الحدّ الأدنى K للطرفين، أقصى تداخلٍ يُطلق التحذير)."""
    def _int(name: str, default: int) -> int:
        try:
            return max(1, int(os.environ.get(name, str(default)) or default))
        except ValueError:
            return default
    try:
        maxov = float(os.environ.get("SILK_A2_MAX_OVERLAP", "0.0") or "0.0")
    except ValueError:
        maxov = 0.0
    return (_int("SILK_A2_SUPPLIERS_TOPM", 5),
            _int("SILK_A2_MIN_ENTRIES", 3), max(0.0, min(1.0, maxov)))


def supplier_plausibility(hs_code, market_iso3: str, market_m49,
                          year: int) -> dict | None:
    """هل ملفُّ موردي السوق يطابق الرمز HS المحسوم؟ — A2 economic cross-check.

    يعيد `{implausible, overlap, market_suppliers, world_exporters,
    intersection}` أو `None` (صمت: بيانات غير كافية/تعذّر القياس — **فشلٌ آمن
    مفتوح**، نظير `is_top_world_exporter`: لا تحذيرٌ كاذبٌ على قياسٍ متعذّر).

    مجموعتان من كومتريد حيّ (صفر نداء مدفوع، صفر ISO/HS مكتوب صلبًا):
    - **A** موردو السوق الفعليون: `market_imports(...).competitors` (أعلى M
      بالقيمة، مرتَّبون تنازليًا أصلًا) → ISO3 عبر `M49_TO_ISO3`.
    - **B** أكبر مصدّري الرمز عالميًا: `top_world_exporters` (نفس N استشارة
      بلد المنشأ). عتبةُ بياناتٍ كافية: كلا الطرفين ≥ K وإلا صمت.

    `implausible=True` فقط عند `overlap ≤ SILK_A2_MAX_OVERLAP` (افتراضًا 0.0:
    **تفكّكٌ تامٌّ** — صفرٌ من كبار موردي السوق بين أكبر مصدّري الرمز عالميًا).
    """
    hs = "".join(ch for ch in str(hs_code or "") if ch.isdigit())
    iso3 = (market_iso3 or "").strip().upper()
    if not hs or len(iso3) != 3:
        return None
    topm, mink, maxov = _a2_params()
    try:
        from silk_data_layer import M49_TO_ISO3
        from silk_data_layer_v2 import market_imports
        mi = market_imports(hs, market_m49, year) or {}
        suppliers: list[str] = []
        for dp in (mi.get("competitors") or []):
            v = getattr(dp, "value", None) or {}
            i3 = M49_TO_ISO3.get(str(v.get("code") or ""), "")
            if len(i3) == 3 and i3 not in suppliers:
                suppliers.append(i3)
            if len(suppliers) >= topm:
                break
        world = [t["iso3"] for t in
                 top_world_exporters(hs, year, _producer_advisory_topn())]
    except Exception as e:  # noqa: BLE001 — عطل قياس لا يُطلق تحذيرًا كاذبًا
        log.warning("A2 supplier plausibility probe failed: %s", e)
        return None
    # عتبة بياناتٍ كافية (المذكّرة §٣٫٢): طرفٌ هزيلٌ => صمت لا تحذيرٌ هشّ.
    if len(suppliers) < mink or len(world) < mink:
        return None
    wset = set(world)
    inter = [i for i in suppliers if i in wset]
    denom = min(len(suppliers), len(world))
    overlap = round(len(inter) / denom, 2) if denom else 1.0
    return {"implausible": overlap <= maxov, "overlap": overlap,
            "market_suppliers": suppliers, "world_exporters": world,
            "intersection": inter}


# ═══ تغطية العالم (SILK_WORLD_MARKETS) — two-tier world coverage ═══
# الفئة-١: الأسواق المنسّقة (تسجيل محلّي كامل). الفئة-٢: بقية العالم، تُسجَّل
# **حصراً** على بياناتٍ متاحةٍ عالمياً (إجمالي وارداتها من نداء العالم الواحد +
# دخل/سكان البنك الدولي المجمّع) — بلا أيّ قيمة محلية مختلَقة (اتفاقيات/لوجستيات/
# ثقافة): الفجوات تُعلَن حرفياً. Tier-2 = universally-available data only.
# سنة الدراسة الافتراضية — the shared study-year basis. وحدةٌ واحدة يشترك فيها
# ترتيبُ الأسواق (rank_markets) وبوّابةُ التغطية (api._market_in_coverage) فيقيسان
# على **نفس** أساس المستوردين (تدقيق v2، الموجة ١): كان الترتيب يفترض ٢٠٢٢ بينما
# البوّابة تستطلع سنة اليوم-١ (غير منشورة غالباً) فتفشل مفتوحةً دوماً. الآن كلاهما
# يبدأ من هذه السنة ويتدرّج للخلف عبر سُلَّم fallback واحد.
DEFAULT_STUDY_YEAR = int(os.environ.get("SILK_STUDY_YEAR", "2022") or "2022")

_TIER1_N = 38                        # الفئة-١: أعلى n مستورداً (تسجيل كامل)
# سقف الفئة-٢ (اتفاق المالك): ٦٢ فتصير التغطية الكلّية ≈ ١٠٠ سوقاً (٣٨+٦٢).
# الاختيار **ديناميكيّ لكل رمز HS** من نداء العالم الواحد (أكبر مستوردي هذا
# الرمز فعلاً) — قرار المالك المعتمَد بديلاً عن قائمة countries_tier2.csv
# ساكنة: التغطية تتبع تجارة الرمز الحقيقية لا قائمةً يدوية عامة. env يظلّ ضابطاً.
_TIER2_MAX = int(os.environ.get("SILK_WORLD_TIER2_MAX", "62") or "62")
_TIER2_CONF_CAP = 0.5                # سقف ثقة الفئة-٢ (بيانات جزئية بنيوياً)
_WORLD_BUDGET_RESERVE = int(
    os.environ.get("SILK_WORLD_BUDGET_RESERVE", "1") or "1")
# النصّ التعاقدي الحرفي لكل صفّ فئة-٢ (مُختبَر بالمطابقة التامة) — the exact
# contract label stamped on every Tier-2 row (asserted by exact match).
TIER2_LABEL = "تغطية أساسية — بيانات محلية محدودة"


def _world_markets_enabled() -> bool:
    """صمّام المالك — SILK_WORLD_MARKETS=1 يفعّل تغطية العالم (افتراضي مُطفأ)."""
    return os.environ.get("SILK_WORLD_MARKETS", "0").strip() == "1"


def _comtrade_budget_left() -> int:
    """المتبقّي من ميزانية كومتريد اليومية — lazy import (تفادي دورة استيراد).

    فشل القراءة => نعتبر الميزانية متاحة (لا نكسر المسار على عطل قياس) —
    لكن نفاد الميزانية المؤكَّد يُسقط الفئة-٢ (تدهور معلن للفئة-١ فقط).
    """
    try:
        from silk_collectors import comtrade_budget_left
        return comtrade_budget_left()
    except Exception as e:      # noqa: BLE001 — عطل قياس لا يكسر الترتيب
        log.warning("comtrade_budget_left probe failed: %s", e)
        return _WORLD_BUDGET_RESERVE + 1


def _tier2_gather_row(hs_code: str, entry: dict, year: int) -> dict:
    """اجمع صفّ فئة-٢ — a Tier-2 row from the ONE world call + WB (no Comtrade call).

    حجم السوق يُشتَقّ من `entry["total_usd"]` (نداء العالم الواحد، لا نداء لكل
    دولة). الدخل/السكان من البنك الدولي المجمّع (خارج ميزانية كومتريد). موقع
    السعودية والمنافسة **فجوتان معلنتان** — لا يُطلَب تفصيل المورّدين لكل دولةٍ
    في العالم (كلفةً وعقداً)؛ ولا قيمة اتفاقية/لوجستية/ثقافية محلية تُنسَب لسوقٍ
    غير منسَّق. NO local-CSV value ever attributed here — declared gaps only.
    """
    iso3, m49 = entry["iso3"], entry["m49"]
    total = entry.get("total_usd")
    inc = _income_dp(iso3, year)
    pop = population(iso3, year)
    ms = (DataPoint(float(total), "UN Comtrade", _TIER2_CONF_CAP,
                    note=f"إجمالي واردات HS{hs_code} {year} (USD) — {TIER2_LABEL}"
                         " · من نداء استيراد العالم الواحد",
                    retrieved_at=_today(), data_year=_dyear(year))
          if total is not None else
          DataPoint(None, "UN Comtrade", 0.0,
                    note=f"{TIER2_LABEL} — لا إجمالي واردات لهذا السوق",
                    retrieved_at=_today(), status="no_record"))
    comp_dps = {
        "market_size": ms,
        "saudi_position": DataPoint(
            None, "UN Comtrade", 0.0,
            note=f"{TIER2_LABEL} — تفصيل المورّدين غير مطلوب لسوقٍ غير منسَّق "
                 "(فجوة معلنة لا صفر مختلَق)",
            retrieved_at=_today(), status="tier2_gap"),
        "demand_capacity": _demand_capacity_component(inc, iso3, year),
        "competition": DataPoint(
            None, "UN Comtrade", 0.0,
            note=f"{TIER2_LABEL} — لا رصد لتركّز المورّدين (فجوة معلنة)",
            retrieved_at=_today(), status="tier2_gap"),
    }
    return {
        "iso3": iso3, "m49": m49,
        "iso2": ISO2.get(iso3),      # قد يكون None لدولٍ خارج خريطة سِلك
        "components": comp_dps,
        "income_ppp": inc.value,
        "population": pop.value,
        "year_used": year, "year_fell_back": False,
        "competitors": [], "top_competitor": None,
        "tier": 2, "coverage": TIER2_LABEL,
    }


# أوزان المكوّنات — tunable component weights (sum ~1.0). Audit/tune here.
WEIGHTS: dict[str, float] = {
    "market_size": 0.40,      # how much the market imports of this HS
    "saudi_position": 0.20,   # Saudi already a supplier? higher = warmer entry
    "demand_capacity": 0.25,  # income (PPP) x population
    "competition": 0.15,      # fragmented suppliers => easier => higher
}


def _market_size_component(total_usd: object, hs_code: str, m49: str,
                           year: int, xval: str = "",
                           fetch_failed: bool = False) -> DataPoint:
    """حجم السوق — total imports of this HS by the market, derived from the SAME
    Comtrade call as the competitors (no extra request). None => no data."""
    if total_usd is None:
        if fetch_failed:   # 1b: عجز جلب ≠ سوق فارغ — «أعد المحاولة» لا «—»
            return DataPoint(None, "UN Comtrade", 0.0,
                             note="تعذّر الجلب من كومتريد (حد معدل/شبكة) — "
                                  "أعد المحاولة",
                             retrieved_at=_today(), status="fetch_failed")
        return DataPoint(None, "UN Comtrade", 0.0,
                         note=f"no import total HS{hs_code} -> {m49} {year}",
                         retrieved_at=_today(), status="no_record")
    conf = 0.7 if xval else 0.9      # تباين مصادر >20% => ثقة أدنى (Stage 2A)
    return DataPoint(float(total_usd), "UN Comtrade", conf,
                     note=f"total imports HS{hs_code} {year} (USD){xval}",
                     retrieved_at=_today(), data_year=_dyear(year))


def _competitor_list(comps: list[DataPoint], top: int = 5) -> list[dict]:
    """قائمة المنافسين للوحة — top suppliers (name + share + value) for the UI.

    `comps` is ranked desc; returns plain dicts (never fabricated; [] if none)."""
    out: list[dict] = []
    for c in comps[:top]:
        if c.value:
            out.append({"partner": c.value.get("partner"),
                        "code": c.value.get("code"),
                        "value_usd": c.value.get("value_usd"),
                        "share": c.value.get("share")})
    return out


def _saudi_position_component(comps: list[DataPoint]) -> DataPoint:
    """موقع السعودية — Saudi supplier share of this market (0 if absent).

    ثقة واعية بالبَتر (مراجعة المشروع): «غياب السعودية» المستنتَج من قائمة
    شركاء قد تكون مبتورة (طبقة المعاينة محدودة الصفوف) ليس رصداً مباشراً —
    فالصفر المستنتَج يحمل ثقةً أدنى من حصةٍ مرصودة، ويرث الجميعُ خفضَ الثقة
    حين يتباين مجموع الشركاء عن صف العالم (اكتشفه market_imports).
    """
    if not comps:
        return DataPoint(None, "UN Comtrade", 0.0,
                         note="no competitor data", retrieved_at=_today())
    sa = next((c for c in comps if c.value and c.value.get("code") == _SAUDI_M49),
              None)
    base = min((c.confidence for c in comps if c.value), default=0.9)
    if sa:
        share = sa.value.get("share")
        if share is None:  # صف مورّد بلا حصة — فجوة معلنة لا KeyError
            return DataPoint(None, "UN Comtrade", 0.0,
                             note="Saudi supplier row lacks a share value",
                             retrieved_at=_today())
        return DataPoint(share, "UN Comtrade", base,
                         note=f"Saudi share {share}%", retrieved_at=_today())
    return DataPoint(
        0.0, "UN Comtrade", round(min(base, 0.6), 2),
        note=("Saudi not yet a supplier (share 0%) — غيابٌ مستنتَج من قائمة "
              "الموردين المرصودة (قد تكون مبتورة في طبقة المعاينة)"),
        retrieved_at=_today())


def _income_dp(iso3: str, year: int) -> DataPoint:
    """الدخل مرّة واحدة — fetch income ONCE (PPP, GDP fallback).

    يُعاد استعماله لمكوّن طاقة الطلب ولحقل income_ppp باللوحة معاً — كان يُجلب
    مرّتين (Q4)، فيُهدر نداءً/قراءة ذاكرة لكل سوق. Fetched once, reused for both.
    """
    inc = ppp_per_capita(iso3, year)
    if inc.value is None:
        inc = gdp_per_capita(iso3, year)
    return inc


def _demand_capacity_component(inc: DataPoint, iso3: str, year: int) -> DataPoint:
    """طاقة الطلب — القوة الشرائية للفرد من دخل مُجلَب مسبقاً (ثراء السوق، لا حجمه).

    purchasing power PER CAPITA (PPP, GDP/cap fallback), computed from the income
    DataPoint already fetched by _income_dp (no second fetch). NOT multiplied by
    population — that made the largest economies dominate every product.
    """
    if inc.value is None:
        return DataPoint(None, "World Bank", 0.0,
                         note=f"no income data for {iso3} {year}",
                         retrieved_at=_today())
    return DataPoint(float(inc.value), "World Bank", 0.9,
                     note=inc.note, retrieved_at=_today())


# تراجُع سنويّ معلن — بيانات التجارة السنوية تتأخّر سنة–سنتين، فالسنةُ المطلوبة قد
# تكون غير منشورة بعد. نبدأ من min(المطلوبة، السنة الحالية−1) ونتراجع حتى نجد أحدث
# سنةٍ فيها بيانات فعلية (بدل انهيار التحليل إلى 0% لسنةٍ لم تُنشر). لا اختلاق:
# السنة الفعلية تُعلَن في ملاحظة كل مكوّن؛ الفشل الكامل يبقى فجوةً معلنة كالمعتاد.
_MAX_YEAR_FALLBACK = 4


def _imports_with_fallback(hs_code: str, m49: str, iso3: str,
                           year: int) -> tuple[dict, int, bool]:
    """استيراد السوق مع تراجعٍ سنويٍّ معلن — most-recent-year-with-data resolver.

    يعيد (mi، السنة_الفعلية، هل_تراجَعنا). يبدأ من min(المطلوبة، الحالية−1) لتفادي
    استعلام سنةٍ لم تُنشر بعد، ثم يتراجع حتى _MAX_YEAR_FALLBACK. آخرُ محاولةٍ فارغة
    تُعاد بالسنة المطلوبة (فجوة معلنة). Never fabricates — just picks the newest
    published year within the window.
    """
    start = min(year, datetime.date.today().year - 1)
    mi = {"total_usd": None, "competitors": []}
    for back in range(_MAX_YEAR_FALLBACK + 1):
        y = start - back
        try:
            mi = market_imports_cached(hs_code, m49, iso3, y, live=market_imports)
        except Exception as e:  # noqa: BLE001 — سنةٌ تفشل لا توقف التراجُع
            log.warning("imports fallback %s->%s %s failed: %s", hs_code, m49, y, e)
            mi = {"total_usd": None, "competitors": []}
            continue
        if mi.get("total_usd") is not None or mi.get("competitors"):
            return mi, y, (y != year)
    return mi, year, False


def _gather_row(hs_code: str, c: dict, year: int) -> dict:
    """اجمع مكوّنات سوق واحد — all fetches for ONE market (runs in a worker thread).

    مستقل تماماً عن بقية الأسواق (لا حالة مشتركة قابلة للتحوّر)، فيُوزَّع على
    الخيوط بأمان. الدخل يُجلب مرّة واحدة (Q4) ويُعاد استعماله. السنةُ الفعلية
    تُحلّ بتراجعٍ معلن عند غياب بيانات السنة المطلوبة (التجارة تتأخّر سنة–سنتين).
    """
    iso3, m49 = c["iso3"], c["m49"]
    # نداء واحد لكل سوق عبر مخزن الحقائق أولاً (M2) + تراجُع سنويّ معلن عند الغياب.
    mi, eff_year, fell_back = _imports_with_fallback(hs_code, m49, iso3, year)
    comps = mi["competitors"]
    inc = _income_dp(iso3, eff_year)             # الدخل مرّة واحدة (Q4)
    pop = population(iso3, eff_year)
    fb = (f" | بيانات {eff_year} — أحدث سنة منشورة ({year} لم تُنشر بعد)"
          if fell_back else "")
    comp_dps = {
        "market_size": _market_size_component(mi["total_usd"], hs_code, m49,
                                              eff_year,
                                              xval=mi.get("xval_note", "") + fb,
                                              fetch_failed=bool(
                                                  mi.get("fetch_failed"))),
        "saudi_position": _saudi_position_component(comps),
        "demand_capacity": _demand_capacity_component(inc, iso3, eff_year),
        "competition": _competition_component(comps),
    }
    return {
        "iso3": iso3, "m49": m49,
        # iso2 من خريطة سِلك أولاً ثم ما مرّره المستخدم — يغذي Trends (geo)
        # وبحث التسوّق (gl) اللذين كانا يتراجعان لعالمي بصمت (P0-3).
        "iso2": ISO2.get(iso3) or c.get("iso2"),
        "components": comp_dps,
        "income_ppp": inc.value,                 # يُعاد استعمال نفس الجلب
        "population": pop.value,
        "year_used": eff_year, "year_fell_back": fell_back,
        "competitors": _competitor_list(comps),
        "top_competitor": _top_competitor(comps),
    }


def _top_competitor(comps: list[DataPoint]) -> str | None:
    """أكبر مورّد غير سعودي — name of the largest NON-Saudi supplier, else None.

    `comps` is already ranked descending by value_usd, so the first competitor
    whose code != Saudi M49 is the largest non-Saudi supplier. Never fabricates.
    """
    for c in comps:
        if c.value and c.value.get("code") != _SAUDI_M49:
            return c.value.get("partner")
    return None


def _competition_component(comps: list[DataPoint]) -> DataPoint:
    """المنافسة — Herfindahl concentration of suppliers (lower share top = easier).

    يرث الثقةَ من نقاط الموردين نفسها (0.7 عند تباين المقام، 0.9 وإلا) —
    مؤشر تركُّزٍ على قائمةٍ قد تكون مبتورة لا يستحق ثقةً أعلى من مدخلاته.
    """
    if not comps:
        return DataPoint(None, "UN Comtrade", 0.0,
                         note="no competitor data", retrieved_at=_today())
    # HHI من الحصص (0..1) — sum of squared shares; 1 = monopoly, ~0 = fragmented.
    # صفٌّ بلا حصة يُسقَط (لا يُعدّ صفراً) — .get يمنع KeyError كامناً.
    shares = [c.value.get("share") for c in comps if c.value]
    hhi = sum((s / 100.0) ** 2 for s in shares if s is not None)
    conf = min((c.confidence for c in comps if c.value), default=0.9)
    return DataPoint(round(hhi, 4), "UN Comtrade", conf,
                     note=f"supplier HHI over {len(comps)} suppliers",
                     retrieved_at=_today())


def _normalize(raw: dict[str, float], value: float) -> float:
    """طبّع 0..1 — min-max normalize one component across all rows.

    حدّ موثَّق (مراجعة المشروع): hi == lo (سوقٌ واحد له بيانات هذا المكوّن،
    أو تساوى الجميع) يعيد 1.0 — علامة كاملة بحكم ندرة البيانات لا الجدارة.
    لا نغيّر الرياضيات كي لا تنقلب الترتيبات القائمة؛ ثقةُ الصف (المكوّنات
    الناقصة تخفضها) هي حاملُ إشارة الندرة إلى المستهلك.
    """
    vals = [v for v in raw.values() if v is not None]
    if not vals:
        return 0.0
    lo, hi = min(vals), max(vals)
    if hi == lo:
        return 1.0
    return (value - lo) / (hi - lo)


def coverage_year_ladder() -> list[int]:
    """سُلَّم سنوات fallback لاستطلاع التغطية — the year-fallback ladder.

    تدقيق v2 (الموجة ١): كومتريد يتأخّر ~سنة-سنتين، فاستطلاع سنة اليوم-١ وحدها
    (٢٠٢٥ في ٢٠٢٦) يعيد فارغاً غالباً فتفشل البوّابة مفتوحةً. نجرّب سنة-١ ثم سنة-٢
    ثم سنة-٣، ونضمن **سنة الدراسة الافتراضية** في الذيل كي تشترك البوّابة والدراسة
    في أساسٍ واحد (والاختبار «٢٠٢٥ فارغة/٢٠٢٢ ممتلئة => تُحجَب» يعبر لهذا الضمان).
    مرتَّب تنازلياً، بلا تكرار."""
    import datetime as _dt
    y = _dt.date.today().year
    ladder = [y - 1, y - 2, y - 3]
    if DEFAULT_STUDY_YEAR not in ladder:
        ladder.append(DEFAULT_STUDY_YEAR)
    seen: set[int] = set()
    return [yr for yr in ladder if not (yr in seen or seen.add(yr))]


def world_import_totals_resolved(hs_code: str,
                                 years: list[int] | None = None
                                 ) -> tuple[list[dict], int | None]:
    """أوّل سنةٍ تُعيد إجماليات عالم غير فارغة عبر السُّلَّم — (totals, year_used).

    نداءٌ واحدٌ لكلّ سنةٍ حتى أوّل نتيجةٍ غير فارغة (كومتريد أولاً بالمخزن، فالكلفة
    نداءٌ واحدٌ نموذجياً)؛ كلّها فارغة => ([], None) والمستدعي يفشل آمناً مفتوحاً
    كاليوم (عطلٌ عابر لا يحجب سوقاً مشروعاً)."""
    for yr in (years or coverage_year_ladder()):
        totals = world_import_totals(hs_code, yr)
        if totals:
            return totals, yr
    return [], None


def rank_markets(hs_code: str, countries: list[dict] | None = None,
                 year: int = DEFAULT_STUDY_YEAR, max_workers: int = 16,
                 world: bool | None = None) -> list[dict]:
    """رتّب الأسواق لرمز HS — rank markets best-first by a weighted, audited score.

    Each result: {country, iso3, m49, total_score, confidence, components}
    where components[name] = the component DataPoint (provenance + raw value).
    Missing components are skipped and lower that row's confidence; weights are
    renormalized over present components so rows stay comparable. Never fabricates.

    P1: الأسواق تُجمَع **بالتوازي** عبر ThreadPoolExecutor (I/O شبكي حاجب)، وكل
    سوق مستقل فالتطبيع يقع بعد اكتمال الجمع؛ `ex.map` يحفظ الترتيب فالنتيجة
    مطابقة للتسلسلي. الجلسة المجمّعة (silk_data_layer._session) تعيد استعمال
    الاتصالات عبر الخيوط. Markets are gathered concurrently; identical output.

    8c (مواصفة المالك): بلا countries صريحة يُجرَّب أولاً «أكبر المستوردين
    عالمياً» ديناميكياً من كومتريد (تغطية ذاتية الصيانة)؛ فشله/غياب الشبكة
    => تراجع معلن للقائمة المنسّقة COUNTRIES — سلوك اليوم حرفياً.
    SILK_DYNAMIC_MARKETS=0 يعطّل الديناميكي (صمام مالك).
    """
    # تغطية العالم (SILK_WORLD_MARKETS) — نداءُ العالم الواحد يخدم الفئتين معاً:
    # أعلى _TIER1_N مرشَّحاً للفئة-١ (تسجيل كامل، نداء لكل دولة كالمعتاد)، والباقي
    # للفئة-٢ (تسجيل رخيص من نفس النداء + البنك الدولي، صفر نداء كومتريد إضافي).
    # نفاد ميزانية كومتريد => تدهور معلن للفئة-١ المنسّقة فقط (لا تلفيق جزئي).
    world_on = _world_markets_enabled() if world is None else world
    tier2_entries: list[dict] = []
    if countries is None and world_on:
        left = _comtrade_budget_left()
        if left > _WORLD_BUDGET_RESERVE:
            totals = world_import_totals(hs_code, year)   # ← النداء الواحد
            if totals:
                countries = [{"iso3": t["iso3"], "m49": t["m49"]}
                             for t in totals[:_TIER1_N]]
                tier2_entries = totals[_TIER1_N:_TIER1_N + _TIER2_MAX]
                log.info("rank_markets: world coverage — Tier-1 %d + Tier-2 %d "
                         "(one world call, zero extra Comtrade)",
                         len(countries), len(tier2_entries))
        else:
            log.info("rank_markets: Comtrade budget exhausted (%d) — degrading "
                     "to Tier-1 curated only (no Tier-2 fabrication)", left)

    if countries is None and os.environ.get(
            "SILK_DYNAMIC_MARKETS", "1").strip() != "0":
        dyn = top_import_markets(hs_code, year)
        if dyn:
            log.info("rank_markets: dynamic candidates from Comtrade (%d)",
                     len(dyn))
            countries = dyn
    countries = countries or COUNTRIES

    # 1) اجمع المكوّنات الخام لكل دولة بالتوازي — gather raw components concurrently.
    #    الفئة-٢ (إن وُجدت) تُجمَع بنفس المُنفِّذ لكن عبر مسارٍ رخيص بلا نداء كومتريد.
    tasks: list[tuple[bool, dict]] = (
        [(False, c) for c in countries] + [(True, e) for e in tier2_entries])
    workers = max(1, min(max_workers, len(tasks)))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        rows: list[dict] = list(ex.map(
            lambda t: (_tier2_gather_row(hs_code, t[1], year) if t[0]
                       else _gather_row(hs_code, t[1], year)), tasks))

    # 2) جداول القيم الخام لكل مكوّن عبر الدول — per-component raw value tables.
    raw_tables: dict[str, dict[str, float]] = {k: {} for k in WEIGHTS}
    for row in rows:
        for name, dp in row["components"].items():
            if dp.value is not None:
                raw_tables[name][row["iso3"]] = float(dp.value)

    # 3) طبّع، اقلب المنافسة (أقل تركّز = أفضل)، ثم وزّن — normalize + weight.
    out: list[dict] = []
    for row in rows:
        iso3 = row["iso3"]
        wsum, score, present = 0.0, 0.0, 0
        for name, w in WEIGHTS.items():
            dp = row["components"][name]
            if dp.value is None:
                continue  # مفقود => يُتخطى، لا قيمة وهمية — skip, no fake value
            norm = _normalize(raw_tables[name], float(dp.value))
            if name == "competition":
                norm = 1.0 - norm  # تركّز أعلى = أصعب — invert: less concentrated better
            score += w * norm
            wsum += w
            present += 1
        # وزّن على المكوّنات الموجودة فقط — renormalize over present weights.
        total = round(score / wsum, 4) if wsum else 0.0
        # ثقة الصف تنخفض بنقص المكوّنات — confidence drops with missing components.
        confidence = round(present / len(WEIGHTS), 2)
        tier = row.get("tier", 1)
        if tier == 2:            # الفئة-٢ مُقيَّدة الثقة بنيوياً (بيانات جزئية)
            confidence = round(min(confidence, _TIER2_CONF_CAP), 2)
        entry = {
            "country": _name(iso3, row["m49"]),
            "iso3": iso3, "m49": row["m49"],
            "iso2": row.get("iso2"),   # يغذي Trends geo وبحث التسوّق gl (P0-3)
            "total_score": total, "confidence": confidence,
            "components": row["components"],
            "income_ppp": row["income_ppp"],
            "population": row["population"],
            "year_used": row.get("year_used"),
            "year_fell_back": row.get("year_fell_back", False),
            "competitors": row["competitors"],
            "top_competitor": row["top_competitor"],
            "tier": tier,
        }
        if tier == 2:
            entry["coverage"] = row.get("coverage", TIER2_LABEL)
        out.append(entry)

    # الفئة-١ أولاً دائماً ثم الفئة-٢ (التغطية الأساسية لا تزحزح المنسّق) — كلٌّ
    # داخلياً بالنقاط ثم الثقة. فالعرض الافتراضي (أعلى ٣) يبقى فئةً-١ حرفياً.
    # Tier-1 always precedes Tier-2 so the default top-N view is unchanged.
    out.sort(key=lambda r: (r.get("tier", 1),
                            -r["total_score"], -r["confidence"]))
    return out


def _name(iso3: str, m49: str) -> str:
    """اسم الدولة — friendly name via the data layer's partner map."""
    from silk_data_layer import partner_name
    n = partner_name(m49)
    return n if n != str(m49) else iso3


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Silk market ranker — demo (degrades gracefully offline)")
    sample = [{"iso3": "ARE", "m49": "784"}, {"iso3": "USA", "m49": "840"}]
    ranked = rank_markets("100630", countries=sample, year=2022)  # rice
    for i, r in enumerate(ranked, 1):
        present = sum(1 for dp in r["components"].values() if dp.value is not None)
        print(f"  {i}. {r['country']:<22} score={r['total_score']:.3f} "
              f"conf={r['confidence']} ({present}/{len(WEIGHTS)} components present)")
    if all(c.value is None for r in ranked for c in r["components"].values()):
        print("  (offline: all components missing -> scores 0, rank still ran)")
