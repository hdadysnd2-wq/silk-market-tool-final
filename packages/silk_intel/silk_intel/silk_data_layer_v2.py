"""طبقة بيانات سِلك (v2) — derived indicators & competitor analysis.

Builds on silk_data_layer with PPP income and market-competitor ranking.
Same rule: never fabricate; failures degrade to provenance-tagged None / [].
"""
from __future__ import annotations

import logging

from silk_data_layer import (
    DataPoint,
    ISO3_TO_M49,
    M49_TO_ISO3,
    comtrade_trade,
    partner_name,
    primary_value,
    world_bank,
    _today,
)

log = logging.getLogger(__name__)

_SAUDI_M49 = "682"


def mirror_saudi_export(hs_code: str, target_m49: object, target_iso3: str,
                        year: int) -> DataPoint:
    """صادرات سعودية مباشرة (مرآة) — Saudi Arabia's OWN reported exports to a
    target market (Comtrade reporter=SAU, flow=X).

    تقنية «إحصاءات المرآة» في اقتصاد التجارة: يقارَن هذا بتقرير السوق الهدف
    عن وارداته من السعودية (reporter=target, partner=SAU) — تقريران مستقلان
    لنفس التدفق التجاري من جهتين جمركيتين مختلفتين، يُستخدمان للتثليث
    (`silk_research._triangulate`) حين يغيب أحدهما أو يتباعدان. لا مصدر
    جديد — Comtrade نفسه، منظور إبلاغ مختلف فقط؛ فشل/غياب => DataPoint(None)
    موسوم (المبدأ التأسيسي: لا اختلاق).
    """
    src = "UN Comtrade (تقرير سعودي مباشر — مرآة)"
    try:  # المخزن أولاً — صف X (reporter=SAU) مخزّن = صفر نداء خارجي.
        import silk_store
        row = silk_store.get_trade_flow(hs_code, "SAU", target_iso3,
                                        int(year), flow="X")
        if row and row.get("value_usd") is not None:
            try:
                import silk_context
                silk_context.count_data("store_hits")
            except Exception:  # noqa: BLE001
                pass
            day = (row.get("retrieved_at") or "")[:10]
            return DataPoint(
                {"value_usd": row["value_usd"], "qty_kg": row.get("qty_kg")},
                src + " — من المخزن", 0.9,
                f"صادرات سعودية مُعلنة مباشرة (reporter=SAU) HS{hs_code}→"
                f"{target_iso3} {year} — من المخزن"
                + (f"، جُلبت أصلاً {day}" if day else ""),
                row.get("retrieved_at") or _today())
    except Exception as e:  # noqa: BLE001 — المخزن تحسين لا شرط
        log.debug("mirror store read unavailable (%s %s %s): %s",
                  hs_code, target_iso3, year, e)

    recs = comtrade_trade(hs_code, _SAUDI_M49, year, flow="X",
                          partner=target_m49) or []
    pairs = [(primary_value(r), r.get("netWgt")) for r in recs]
    pairs = [(v, q) for v, q in pairs if v is not None]
    if not pairs:
        return DataPoint(
            None, src, 0.0,
            f"لا تقرير سعودي مباشر (reporter=SAU) لـ HS{hs_code}→{target_iso3} "
            f"{year} — مرآة غير متاحة", _today())
    total_usd = sum(v for v, _ in pairs)
    qtys = [float(q) for _, q in pairs if q]
    try:  # كتابة عابرة — التحليل التالي لنفس الثلاثية يقرأ من المخزن مجاناً.
        import silk_store
        silk_store.migrate()
        silk_store.upsert_trade_flows([{
            "hs6": hs_code, "reporter_iso3": "SAU",
            "partner_iso3": target_iso3, "year": int(year), "flow": "X",
            "value_usd": total_usd, "qty_kg": sum(qtys) if qtys else None}])
    except Exception as e:  # noqa: BLE001 — never break the live path
        log.warning("mirror write-through failed (%s %s %s): %s",
                    hs_code, target_iso3, year, e)
    return DataPoint(
        {"value_usd": total_usd, "qty_kg": sum(qtys) if qtys else None}, src, 0.9,
        f"صادرات سعودية مُعلنة مباشرة (reporter=SAU) HS{hs_code}→{target_iso3} "
        f"{year}", _today())


def ppp_per_capita(iso3: str, year: int | None = None) -> DataPoint:
    """نصيب الفرد (تعادل القوة الشرائية) — GDP per capita, PPP (current int'l $)."""
    return world_bank(iso3, "NY.GDP.PCAP.PP.CD", year)


def _competitor_dp(code: object, value_usd: float, grand: float, *,
                   hs_code: str, market_label: object, year: int,
                   source: str = "UN Comtrade",
                   confidence: float = 0.9, note_suffix: str = "",
                   retrieved_at: str | None = None) -> DataPoint:
    """نقطة مورّدٍ موحّدة — the ONE competitor-DataPoint constructor.

    كان الشكل {partner, code, value_usd, share} يُبنى في ثلاثة مواضع
    (market_imports، مسار المخزن، والمُرتِّب يستهلكه) — توحيدُه يمنع انحرافها.
    `retrieved_at` يُمرَّر لقراءات المخزن بتاريخ **الجلب الأصلي** — قراءة
    مخزّنة لا تُختم بتاريخ اليوم كأنها حية (قاعدة الإسناد).
    """
    share = round(100 * value_usd / grand, 2)
    return DataPoint(
        value={"partner": partner_name(code), "code": str(code),
               "value_usd": value_usd, "share": share},
        source=source, confidence=confidence,
        note=(f"HS{hs_code} imports to {market_label} {year}; "
              f"share {share}%{note_suffix}"),
        retrieved_at=retrieved_at or _today(),
        # سنة البيانات البنيوية (الدرس ٣٣) — لا وسم نصّيّ في الملاحظة.
        data_year=int(year) if str(year).isdigit() else None)


def market_imports(hs_code: str, market_m49: object, year: int) -> dict:
    """واردات سوق ومنافسوه من نداء Comtrade واحد — ONE call: total imports + suppliers.

    يجمع الكفاءة: الردّ نفسه يحوي صفّ «العالم» (إجمالي الواردات = حجم السوق) وصفوف
    الشركاء (المنافسون). فتغني هذه الدالة عن نداءٍ ثانٍ لحجم السوق، وتقلّ نداءات
    Comtrade للنصف — أهمّ سبب لغياب النتائج بلا مفتاح (سقف المعاينة منخفض).

    Returns {"total_usd": float|None, "competitors": [DataPoint{partner,code,
    value_usd,share}]} — competitors ranked desc by value, share = % of suppliers
    total. Empty/failed -> {"total_usd": None, "competitors": []}. Never fabricates.
    """
    recs = comtrade_trade(hs_code, market_m49, year, flow="M", partner="all")
    if recs is None:
        # 1b: تعذّر الجلب (429/شبكة) — يميَّز عن الغياب الحقيقي حتى لا يُعرض
        # سوق موجودة بياناته فعلاً كأنه فارغ (بلاغ سنغافورة 17.4M$).
        log.warning("market_imports: fetch FAILED (%s -> market %s, %s)",
                    hs_code, market_m49, year)
        return {"total_usd": None, "competitors": [], "fetch_failed": True}
    if not recs:
        log.warning("market_imports: no data (%s -> market %s, %s)",
                    hs_code, market_m49, year)
        return {"total_usd": None, "competitors": []}
    # جمع حسب الشريك مع التقاط صفّ العالم — aggregate per partner; capture World row.
    world: float | None = None
    totals: dict[str, float] = {}
    for rec in recs:
        code = str(rec.get("partnerCode"))
        val = primary_value(rec)
        if val is None:  # سجل بلا قيمة رقمية لا يُعدّ صفراً — لا اختلاق منافس بـ0$
            continue
        if code == "0":  # World aggregate = total market imports (market size)
            world = val
            continue
        totals[code] = totals.get(code, 0.0) + val
    grand = sum(totals.values())
    # حجم السوق: الأكبر رياضياً بين صف العالم ومجموع الشركاء (مراجعة المشروع).
    # ثابت رياضي لا يقبل النقاش: الإجمالي لا يمكن أن يصغر عن مجموع جزءٍ منه —
    # فحين world < grand يكون صف العالم خاطئاً/غير مكتمل يقيناً (لا نخمّن أيّهما
    # أصحّ، بل نستبعد المستحيل حسابياً). كان الكود يفضّل صف العالم دائماً ولو
    # كان أصغر بعشرات الأضعاف من مجموع شركاء مرصودين بالاسم في نفس الردّ —
    # تناقضٌ داخل التقرير نفسه (TAM يخالف جدول المنافسين وخط الاتجاه) يفقد
    # الثقة فوراً. الحالة world>=grand (الأشيع: مجموع شركاء ناقص لصغار الدول)
    # سلوكها كالسابق تماماً؛ لا انحدار.
    total_usd = None
    if world and world > 0:
        total_usd = world
    if grand > 0 and (total_usd is None or grand > total_usd):
        total_usd = grand
    # تحقق تقاطعي (Stage 2A): مشتقّتان لنفس الحقيقة — صف العالم ومجموع الشركاء.
    # تباين >20% يُعلَّم (سوء تبويب/نقص شركاء محتمل) ولا يُخفى ولا يُسوّى.
    xval_note = ""
    if world and world > 0 and grand > 0:
        div = abs(world - grand) / world
        if div > 0.20:
            xval_note = (f" | تباين مصادر {round(100 * div)}%: صف العالم "
                         f"{round(world):,}$ مقابل مجموع الشركاء {round(grand):,}$")
            if grand > world:
                xval_note += " — استُخدم مجموع الشركاء (الأكبر؛ صف العالم أصغر من مجموع جزءٍ منه، مستحيل حسابياً)"
    competitors: list[DataPoint] = []
    if grand > 0:
        # ثقة واعية بالبَتر (مراجعة المشروع): الحصص تُقسم على مجموع الشركاء
        # المرصودين — وطبقة المعاينة محدودة الصفوف، فمقامٌ متباينٌ عن صف
        # العالم (>20%) يعني احتمال شركاء ساقطين وحصصاً منتفخة. لا نخفي
        # الرقم (لا اختلاق عكسي) بل نخفض ثقته ونعلن السبب في الملاحظة.
        comp_conf = 0.7 if xval_note else 0.9
        comp_note = (" | الحصة على مجموعٍ قد يكون ناقصاً (تباين صف العالم)"
                     if xval_note else "")
        for code, val in sorted(totals.items(), key=lambda kv: kv[1], reverse=True):
            competitors.append(_competitor_dp(
                code, val, grand, hs_code=hs_code, market_label=market_m49,
                year=year, confidence=comp_conf, note_suffix=comp_note))
    return {"total_usd": total_usd, "competitors": competitors,
            "xval_note": xval_note}


def market_competitors(hs_code: str, market_m49: object, year: int) -> list[DataPoint]:
    """المنافسون في السوق — suppliers of an HS code to a market, ranked by value.

    Thin wrapper over market_imports() (kept for the agents). Each DataPoint.value
    is {partner, code, value_usd, share}, ranked desc; [] on failure.
    """
    return market_imports(hs_code, market_m49, year)["competitors"]


def market_competitors_mirror(hs_code: str, market_m49: object,
                              year: int) -> list[DataPoint]:
    """تقدير مرآة لمورّدي سوق لا يُبلِغ كومتريد عن نفسه — mirror fallback
    (ترقية المرحلة ٢ج، خيار A): بدل سؤال السوق «من استوردتِ منه؟» (استعلام
    market_imports() المباشر، reporter=السوق)، اسأل كل الدول الأخرى «كم
    صدّرتِ لهذه السوق؟» (comtrade_trade بـreporter='all',
    partner=السوق, flow='X') — نفس تقنية mirror_saudi_export أعلاه لكن
    معمَّمة لكل مورّد لا لسعودية فقط، فتعيد صورة تنافسية كاملة (حصص +
    HHI قابل للحساب) حتى حين لا تُبلِغ السوق الهدف عن نفسها إطلاقاً.

    ثقة أدنى دوماً من market_competitors المباشر (0.6 لا 0.9-0.7) — تباين
    تصريحات استيراد/تصدير معروف إحصائياً (قيمة CIF مقابل FOB، توقيت
    الشحنة، إعادة التصدير عبر ميناء ثالث)، وكل بند موسوم صراحة في المصدر
    والملاحظة («مرآة»). يُستدعى فقط حين يعيد market_competitors [] — لا
    استبدال للاستعلام المباشر، احتياط عند غيابه فقط. Never fabricates:
    [] أيضاً حين يعيد استعلام المرآة نفسه فراغاً.
    """
    recs = comtrade_trade(hs_code, "all", year, flow="X", partner=market_m49)
    if not recs:
        return []
    totals: dict[str, float] = {}
    for rec in recs:
        code = str(rec.get("reporterCode") or "")
        val = primary_value(rec)
        if val is None or not code:
            continue
        totals[code] = totals.get(code, 0.0) + val
    grand = sum(totals.values())
    if grand <= 0:
        return []
    return [
        _competitor_dp(
            code, val, grand, hs_code=hs_code, market_label=market_m49,
            year=year, source="UN Comtrade (مرآة)", confidence=0.6,
            note_suffix=" — تقدير مرآة من تصريحات تصدير الشركاء (السوق لا "
                       "تُبلِغ كومتريد مباشرة لهذه السنة/الرمز)")
        for code, val in sorted(totals.items(), key=lambda kv: kv[1], reverse=True)]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Silk data layer v2 — demo (degrades gracefully offline)")
    dp = ppp_per_capita("SAU")
    if dp.value is None:
        print(f"  PPP/capita SAU: no data / fetch failed — {dp.note}")
    else:
        print(f"  PPP/capita SAU = {dp.value} int'l$ [{dp.source}, {dp.note}]")
    comps = market_competitors("100630", 840, 2022)  # rice into USA
    if not comps:
        print("  Competitors: no data / fetch failed")
    else:
        print(f"  Top supplier: {comps[0].value['partner']} "
              f"({comps[0].value['share']}%)")


# ── M2: قراءة من مخزن الحقائق أولاً + كتابة عابرة — store-first + write-through ──

def _write_through_market(mi: dict, hs_code: str, market_iso3: str,
                          year: int) -> None:
    """كتابة عابرة لنتيجة حية ناجحة — write a successful live result through.

    يستعمله المسار الرئيسي وتحديثُ الخلفية معاً. فشلها لا يكسر شيئاً —
    المخزن تحسين لا شرط. Shared by the main path and the SWR background job.
    """
    try:
        if mi["total_usd"] is not None or mi["competitors"]:
            import silk_store
            rows = []
            if mi["total_usd"] is not None:
                rows.append({"hs6": hs_code, "reporter_iso3": market_iso3,
                             "partner_iso3": "WLD", "year": int(year), "flow": "M",
                             "value_usd": mi["total_usd"]})
            for c in mi["competitors"]:
                v = c.value or {}
                piso = M49_TO_ISO3.get(str(v.get("code")), str(v.get("code")))
                rows.append({"hs6": hs_code, "reporter_iso3": market_iso3,
                             "partner_iso3": piso, "year": int(year), "flow": "M",
                             "value_usd": v.get("value_usd")})
            if rows:
                silk_store.migrate()
                silk_store.upsert_trade_flows(rows)
    except Exception as e:  # noqa: BLE001 — never break the live path
        log.warning("fact-store write-through failed (%s %s %s): %s",
                    hs_code, market_iso3, year, e)


def _swr_refresh(hs_code: str, market_m49: object, market_iso3: str,
                 year: int, live=None) -> None:
    """جسم تحديث الخلفية — the synchronous stale-while-revalidate job.

    جلب حي + كتابة عابرة؛ فشل الجلب يترك القيمة العتيقة كما هي (تبقى معلَّمة
    stale — لا حجب ولا اختلاق). Live fetch + write-through; failure keeps the
    stale value declared as such.
    """
    try:
        mi = (live or market_imports)(hs_code, market_m49, year)
        if not mi.get("fetch_failed"):
            _write_through_market(mi, hs_code, market_iso3, year)
    except Exception as e:  # noqa: BLE001 — تحديث الخلفية لا يُسقط شيئاً
        log.debug("SWR refresh failed (%s %s %s): %s",
                  hs_code, market_iso3, year, e)


def _refresh_in_background(hs_code: str, market_m49: object, market_iso3: str,
                           year: int, live=None) -> None:
    """أطلق تحديث الخلفية — spawn the SWR daemon thread (SILK_SWR=0 disables)."""
    import os
    if os.environ.get("SILK_SWR", "").strip() == "0":
        return
    import threading
    threading.Thread(target=_swr_refresh, name="silk-swr", daemon=True,
                     args=(hs_code, market_m49, market_iso3, year, live)).start()


def market_imports_cached(hs_code: str, market_m49: object, market_iso3: str,
                          year: int, live=None) -> dict:
    """واردات سوق عبر مخزن الحقائق أولاً — fact-store first, live+write-through miss.

    نفس عقد market_imports تماماً. وجود صفوف للسنة/الرمز في المخزن = إصابة (صفر
    نداء خارجي)؛ الغياب = المسار الحي القائم، وعند نجاحه تُكتب الصفوف للمخزن
    فيستفيد كل تحليل لاحق. أي فشل في طبقة المخزن يسقط بأمان للمسار الحي — المخزن
    تحسين، ليس شرطاً. لا اختلاق: مخزن فارغ لا يُنتج صفوفاً.

    سياسة الحداثة (persist-4): إصابة داخل النافذة تُخدم كما هي (freshness=
    "fresh")؛ العتيقة تُخدم **فوراً** معلَّمة stale (في الإسناد وstatus كل
    نقطة) ويُطلَق تحديث بالخلفية — لا تُعرض قيمة مخزّنة كجلب حي أبداً.
    الحالات الأربع متمايزة للمستهلك: fresh / stale (معروضة معلَّمة) /
    fetch_failed (حي تعذّر — أعد المحاولة) / no_record (غياب حقيقي).
    """
    try:  # 1) المخزن أولاً — the warm store
        import silk_store
        got = silk_store.market_imports_from_store(hs_code, market_iso3, int(year))
        if got["total_usd"] is not None or got["partners"]:
            # صفٌّ مخزّن بقيمة None لا يُجمَع (كان يرمي TypeError فيُهدر
            # المخزنُ الدافئ كلُّه صامتاً إلى المسار الحي) ولا يُعدّ صفراً.
            valued = [p for p in got["partners"]
                      if p.get("value_usd") is not None]
            grand = sum(p["value_usd"] for p in valued) or None
            fetched = got.get("retrieved_at")
            fetched_day = (fetched or "")[:10]
            state = silk_store.freshness(fetched, "trade")
            stale = state != "fresh"
            stale_note = (" — أقدم من نافذة الحداثة؛ يجري تحديثها بالخلفية"
                          if stale else "")
            competitors = []
            if grand:
                for p in valued:
                    m49 = ISO3_TO_M49.get(p["iso3"], p["iso3"])
                    p_day = (p.get("retrieved_at") or fetched or "")[:10]
                    competitors.append(_competitor_dp(
                        m49, p["value_usd"], grand, hs_code=hs_code,
                        market_label=market_iso3, year=year,
                        source="UN Comtrade (مخزن الحقائق)",
                        note_suffix=(" — من المخزن"
                                     + (f"، جُلبت أصلاً {p_day}" if p_day else "")
                                     + stale_note),
                        retrieved_at=p.get("retrieved_at") or fetched))
                    if stale:
                        competitors[-1].status = "stale"
            if stale:  # تُخدم فوراً وتُحدَّث بالخلفية — serve now, refresh behind
                _refresh_in_background(hs_code, market_m49, market_iso3,
                                       int(year), live)
            try:  # عدّاد اقتصاد البيانات — إصابة مخزن (شفافية لا شرط)
                import silk_context
                silk_context.count_data("store_hits")
            except Exception:  # noqa: BLE001
                pass
            return {"total_usd": got["total_usd"], "competitors": competitors,
                    "xval_note": "", "served_from": "store",
                    "freshness": "stale" if stale else "fresh",
                    "retrieved_at": fetched,
                    "provenance_note": ("من المخزن"
                                        + (f" — جُلبت أصلاً {fetched_day}"
                                           if fetched_day else "")
                                        + stale_note)}
    except Exception as e:  # noqa: BLE001 — المخزن تحسين لا شرط (هدوء: debug)
        log.debug("fact-store read unavailable (%s %s %s): %s",
                  hs_code, market_iso3, year, e)

    # 2) المسار الحي القائم — the existing live path. `live` يُمرَّر من المُرتِّب
    # ليبقى قابلاً للترقيع في اختباراته (wave8 seam) — default: هذا الملف.
    mi = (live or market_imports)(hs_code, market_m49, year)
    mi.setdefault("served_from", "live")

    # 3) كتابة عابرة عند النجاح — write-through so the NEXT run is store-warm.
    _write_through_market(mi, hs_code, market_iso3, year)
    return mi
