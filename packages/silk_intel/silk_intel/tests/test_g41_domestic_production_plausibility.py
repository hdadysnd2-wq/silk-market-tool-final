"""قفلُ G4.1 (DEF-1) — حارسُ المعقولية يقرأ الإنتاجَ المحليّ من البروفايل.

الباعث: الحارسُ (HF3) افترض «حجم السوق ≈ الواردات» — صحيحٌ لقطر (إنتاجٌ محليٌّ
ضئيل) لكنّه **خطأٌ لنيجيريا والهند** حيث حجمُ سوقٍ يفوق الواردات بأضعافٍ مشروعٌ
لأنّ الفول السودانيّ (groundnuts) يُزرَع محلياً. كان الحارسُ يتّهم رقماً صحيحاً
زوراً (يُحفّظ عليه أو يُسقطه) — عكسُ العيب: تشويهُ حقيقةٍ لا اختلاقُ رقم.

الإصلاح (G4.1، حاملُ #169): `product.production_category ∈
market.domestic_production` ⇒ إعفاءُ مقدار حجم السوق من كلا الأرمَين. قطر
(domestic_production=[]) تبقى مضبوطة. هرمتيّ: يقرأ ملفّي البروفايل فقط، صفر شبكة.
"""
import silk_plausibility as P
import silk_profiles as SP

_HS_PB = "200811"  # زبدة الفول السوداني — production_category=groundnuts


def _blob(iso3: str, market_usd: str, imports_usd: str, pop: str | None = None):
    """نتيجةُ بحثٍ مصغّرة: مقدارُ حجم سوقٍ + مرتكزُ واردات (+ سكان اختياري)."""
    findings = [
        {"value": imports_usd, "source": "UN Comtrade",
         "note": f"إجمالي استيراد {iso3} من العالم"},
        {"value": market_usd, "source": "ويب", "note": "حجم السوق الكامل"},
    ]
    if pop:
        findings.append({"value": pop, "source": "World Bank",
                         "note": "عدد السكان"})
    return {"market": {"iso3": iso3}, "hs_code": _HS_PB,
            "deep_research": {"missions": {"m": {"findings": findings}}}}


# ── لبُّ العيب: سوقٌ مُنتِجة لا تُوسَم؛ سوقٌ غيرُ مُنتِجة تبقى مضبوطة ──────────

def test_producer_market_not_flagged_nigeria():
    """نيجيريا تُنتِج الفول السودانيّ ⇒ 497م$ مقابل واردات 7م$ **مشروع**، لا علامة."""
    flags = P.check_magnitudes(_blob("NGA", "497 مليون دولار", "7,000,000 دولار"))
    assert flags == [], f"سوقٌ مُنتِجة وُسِمت زوراً: {flags}"


def test_producer_market_not_flagged_india():
    flags = P.check_magnitudes(_blob("IND", "2.5 مليار دولار", "10,000,000 دولار"))
    assert flags == [], f"الهند (مُنتِجة) وُسِمت زوراً: {flags}"


def test_non_producer_market_still_flagged_qatar():
    """قطر لا تُنتِج (domestic_production=[]) ⇒ 497م$ مقابل 7م$ يبقى مُوسَماً."""
    flags = P.check_magnitudes(_blob("QAT", "497 مليون دولار", "7,000,000 دولار"))
    assert flags, "قطر (غير مُنتِجة) يجب أن تبقى مضبوطة — انحدار!"
    assert flags[0]["detail"]["import_ratio"] > 20


def test_non_producer_market_still_flagged_netherlands():
    """هولندا لا تُنتِج الفول السودانيّ (groundnuts ليست في قائمتها) ⇒ يُوسَم."""
    flags = P.check_magnitudes(_blob("NLD", "497 مليون دولار", "7,000,000 دولار"))
    assert flags, "هولندا (لا تُنتِج هذا المنتج) يجب أن تبقى مضبوطة"


# ── الحامل: قراءةُ البروفايل صحيحة ──────────────────────────────────────────

def test_helper_reads_domestic_production_from_profiles():
    assert P._domestic_production_significant(
        {"market": {"iso3": "NGA"}, "hs_code": _HS_PB})[0] is True
    assert P._domestic_production_significant(
        {"market": {"iso3": "IND"}, "hs_code": _HS_PB})[0] is True
    assert P._domestic_production_significant(
        {"market": {"iso3": "QAT"}, "hs_code": _HS_PB})[0] is False
    assert P._domestic_production_significant(
        {"market": {"iso3": "NLD"}, "hs_code": _HS_PB})[0] is False


# ── فشلٌ آمنٌ محافِظ: بلا سوق/رمز/بروفايل ⇒ السلوكُ القديم (لا انحدار) ────────

def test_fail_safe_without_market_or_hs_preserves_old_behavior():
    """بلا `market`/`hs_code` في النتيجة ⇒ لا إعفاء ⇒ يُوسَم كما كان."""
    result = {"deep_research": {"missions": {"m": {"findings": [
        {"value": "7,000,000 دولار", "source": "UN Comtrade",
         "note": "إجمالي استيراد قطر من العالم"},
        {"value": "497 مليون دولار", "source": "ويب",
         "note": "حجم السوق الكامل"}]}}}}
    assert result.get("market") is None
    flags = P.check_magnitudes(result)
    assert flags, "بلا سوق: يجب أن يبقى السلوكُ القديم (يُوسَم)"


def test_fail_safe_unprofiled_market_not_exempt():
    """سوقٌ بلا بروفايل ⇒ لا إعفاء (محافِظ) — لا يُخفي علامةً حقيقية."""
    ok, reason = P._domestic_production_significant(
        {"market": {"iso3": "ZZZ"}, "hs_code": _HS_PB})
    assert ok is False and "بروفايل" in reason


def test_exemption_recorded_in_manifest_visible_to_reviewer():
    """الإعفاءُ مرئيٌّ في المانيفست («guard_relaxed_domestic_producer»)، لا صامت —
    فيرى المراجعُ أنّ الحارسَ وقف جانباً ولماذا (طلبُ المالك: graduation)."""
    result = _blob("NGA", "497 مليون دولار", "7,000,000 دولار")
    flags = P.annotate(result)
    assert flags == [], "سوقٌ مُنتِجة: لا علامةَ عميل"
    exempt = result["deep_research"].get("plausibility_exemptions")
    assert exempt, "الإعفاءُ يجب أن يُسجَّل في المانيفست — لا يختفي"
    assert exempt[0]["kind"] == "guard_relaxed_domestic_producer"
    assert exempt[0]["severity"] == "info"


def test_exemption_is_not_a_client_caveat():
    """المانيفستُ للمراجع لا للعميل — الإعفاءُ لا يتسرّب كتحفّظٍ في تقرير العميل."""
    result = _blob("NGA", "497 مليون دولار", "7,000,000 دولار")
    flags = P.annotate(result)
    # `caveat_lines` تُصيَّر للعميل — تقرأ العلاماتِ فقط لا الإعفاءات.
    assert P.caveat_lines(flags) == []


def test_exemption_logged_via_annotate(caplog):
    import logging
    with caplog.at_level(logging.INFO, logger="silk.plausibility"):
        P.annotate(_blob("NGA", "497 مليون دولار", "7,000,000 دولار"))
    assert any("exempt" in r.message for r in caplog.records)


# ── حراسةٌ على البيانات: البروفايل المستعمَل موجودٌ فعلاً ────────────────────

def test_golden_case_profiles_present():
    """حراسة: نيجيريا/الهند/قطر مُعرَّفة، وزبدة الفول السودانيّ لها
    production_category، وإلا القفلُ أعلاه بلا معنى."""
    for iso in ("NGA", "IND", "QAT"):
        assert SP.market_profile(iso), f"ملفُّ {iso} مفقود"
    pp = SP.product_profile(_HS_PB)
    assert pp and SP.cited_value(pp.get("production_category")) == "groundnuts"
