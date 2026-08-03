"""أقفالُ طبقة التعميم G1/G2 — سجلّا الملامح (market/product profiles).

هرمتيّ بالكامل (قراءةُ ملفَّي YAML + منطقُ تحقّقٍ محلّيّ، صفرُ شبكة). يثبت:
- الملفّان يُحمَّلان ويجتازان التحقّق (كلُّ حقيقةٍ موثَّقةٌ بـsource_url+review_date).
- المُحقِّقُ يمسك: استشهاداً ناقصاً، قيمةَ enum خارجَ المسموح، نطاقاً مقلوباً.
- الملامحُ تغطّي أسواقَ/منتجاتِ الحالات الذهبية الأربع.
- بياناتُ أساسِ G4.1 حاضرة (نيجيريا/الهند تُنتِجان groundnuts، قطر لا) —
  فحارسُ المعقولية القادم يقرؤها بلا فرعٍ خاصٍّ بسوق.

Run:  python3 -m pytest tests/test_profiles_g1_g2.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import silk_profiles as P


# ── التحميل والتحقّق ─────────────────────────────────────────────────────────
def test_all_profiles_load_and_validate():
    assert P.validate_all() == []


def test_four_golden_markets_present():
    assert set(P.all_market_iso3()) >= {"QAT", "NLD", "NGA", "IND"}


def test_two_golden_products_present_by_hs():
    assert P.product_profile("200811") is not None
    assert P.product_profile("080410") is not None
    # مطابقةٌ على hs_code.value لا مفتاح المدخل.
    assert P.cited_value(P.product_profile("200811")["hs_code"]) == "200811"


def test_every_market_fact_is_cited():
    """لا حقيقةٌ بلا source_url+review_date — عقدُ عدم الاختلاق ممتدٌّ للملامح."""
    for iso3 in P.all_market_iso3():
        assert P.validate_market(iso3, P.market_profile(iso3)) == []


def test_every_product_fact_is_cited():
    reg = P._product_registry()
    for key, prof in reg.items():
        assert P.validate_product(key, prof) == []


# ── المُحقِّقُ يمسك المخالفات (البوّابةُ فاعلة) ────────────────────────────────
def test_validator_catches_missing_citation():
    bad = {"QAT": {**P.market_profile("QAT")}}
    # انزع review_date من حقيقةِ العملة.
    ident = {k: dict(v) if isinstance(v, dict) else v
             for k, v in bad["QAT"]["identity"].items()}
    ident["currency"] = {"value": "QAR", "source_url": "https://x"}  # لا review_date
    bad["QAT"] = {**bad["QAT"], "identity": ident}
    errs = P.validate_all(markets=bad, products={})
    assert any("currency.review_date" in e for e in errs)


def test_validator_catches_bad_enum():
    prof = {"QAT": {**P.market_profile("QAT"),
                   "reporting_quality": {"value": "excellent",  # خارج المسموح
                                        "source_url": "https://x",
                                        "review_date": "2026-07-24"}}}
    errs = P.validate_all(markets=prof, products={})
    assert any("reporting_quality" in e and "خارج المسموح" in e for e in errs)


def test_validator_catches_inverted_plausibility_band():
    prod = {"p": {**P.product_profile("200811"),
                 "plausibility_band": {
                     "per_capita_kg_min": {"value": 10.0, "source_url": "https://x",
                                          "review_date": "2026-07-24"},
                     "per_capita_kg_max": {"value": 1.0, "source_url": "https://x",
                                          "review_date": "2026-07-24"}}}}
    errs = P.validate_all(markets={}, products=prod)
    assert any("الحدُّ الأدنى" in e for e in errs)


def test_validator_catches_corridor_without_transit_or_gap():
    prof = {"QAT": {**P.market_profile("QAT"), "logistics": {"corridors": [
        {"origin": "SAU", "destination": "QAT", "mode": "sea",
         "main_port": "Hamad Port", "source_url": "https://x",
         "review_date": "2026-07-24"}]}}}  # مرفأ+استشهاد لكن لا زمن ولا gap
    errs = P.validate_all(markets=prof, products={})
    assert any("gap_reason" in e for e in errs)


def test_validator_requires_corridor_main_port():
    """HIGH-4: بوّابةُ الوجهة (main_port) حقلٌ إلزاميّ — لا تُترَك بلا فحص."""
    prof = {"QAT": {**P.market_profile("QAT"), "logistics": {"corridors": [
        {"origin": "SAU", "destination": "QAT", "mode": "sea",
         "transit_time_days": None, "gap_reason": "WS7",
         "source_url": "https://x", "review_date": "2026-07-24"}]}}}  # لا main_port
    errs = P.validate_all(markets=prof, products={})
    assert any("main_port" in e for e in errs)


def test_production_category_drift_is_rejected():
    """HIGH-5: مفتاحُ انضمام G4.1 مُتحكَّمٌ بمفرداتٍ — «groundnut» (مفرد) يُرفَض
    في **كلا** السجلّين فلا يُعيد علامةَ المعقولية الكاذبة صامتاً."""
    # جانبُ السوق.
    bad_m = {"NGA": {**P.market_profile("NGA"),
                    "domestic_production": {"value": ["groundnut"],  # مفردٌ خاطئ
                                           "source_url": "https://x",
                                           "review_date": "2026-07-24"}}}
    assert any("domestic_production" in e and "خارج المسموح" in e
               for e in P.validate_all(markets=bad_m, products={}))
    # جانبُ المنتج.
    bad_p = {"p": {**P.product_profile("200811"),
                  "production_category": {"value": "peanuts",  # مرادفٌ غير معتمد
                                         "source_url": "https://x",
                                         "review_date": "2026-07-24"}}}
    assert any("production_category" in e and "خارج المسموح" in e
               for e in P.validate_all(markets={}, products=bad_p))


# ── بياناتُ أساسِ G4.1 (المعقولية الواعية بالإنتاج) — حاضرةٌ وصحيحة ────────────
def test_producer_markets_declare_groundnut_production():
    """نيجيريا والهند تُنتِجان الفول السودانيّ محلياً (فحجمُ سوقٍ > الواردات
    مشروعٌ لهما، G4.1)؛ قطر لا (فتعارُضُ الـ497م$ يبقى مُلتقَطاً)."""
    nga = P.cited_value(P.market_profile("NGA")["domestic_production"])
    ind = P.cited_value(P.market_profile("IND")["domestic_production"])
    qat = P.cited_value(P.market_profile("QAT")["domestic_production"])
    assert "groundnuts" in nga and "groundnuts" in ind
    assert "groundnuts" not in qat and qat == []
    # فئةُ إنتاج المنتج تُطابِق قائمةَ السوق (المفتاحُ البياناتيُّ للانضمام).
    assert P.cited_value(P.product_profile("200811")["production_category"]) == "groundnuts"


def test_dates_not_domestically_produced_in_india():
    """الهند تستورد التمور (لا تُنتِجها بكثرة) — فحجمُ سوقِ التمر ≈ الواردات."""
    ind = P.cited_value(P.market_profile("IND")["domestic_production"])
    assert "dates" not in ind
    assert P.cited_value(P.product_profile("080410")["production_category"]) == "dates"


def test_reporting_tiers_match_golden_ceilings_direction():
    """رُتبُ التبليغ توافق سقوفَ الحالات الذهبية: نيجيريا ضعيفةٌ (سقفٌ أعلى)،
    قطر/هولندا قويّتان، الهند متوسّطة."""
    tier = lambda i: P.cited_value(P.market_profile(i)["reporting_quality"])
    assert tier("NGA") == "weak"
    assert tier("QAT") == "strong" and tier("NLD") == "strong"
    assert tier("IND") == "moderate"


def test_gcc_member_tariff_strategy_is_bloc_first():
    """عضوُ الاتحاد الجمركيّ (قطر) يبدأ بمصفوفة الكتلة؛ غيرُ العضو (الهند) بـWITS."""
    qat = P.cited_value(P.market_profile("QAT")["trade_regime"]["tariff_resolution_strategy"])
    ind = P.cited_value(P.market_profile("IND")["trade_regime"]["tariff_resolution_strategy"])
    assert qat[0] == "bloc_matrix"
    assert ind[0] == "wits"


def test_accessors_are_case_insensitive_and_none_safe():
    assert P.market_profile("qat") is P.market_profile("QAT")
    assert P.market_profile("ZZZ") is None
    assert P.product_profile("999999") is None
    assert P.cited_value({"value": 5}) == 5
    assert P.cited_value(None, default="x") == "x"


# ── منطقُ الملامح خالٍ من التخصيص (تمهيدٌ لبوّابة G5) ──────────────────────────
def test_profiles_logic_module_has_no_hardcoded_market_names():
    """silk_profiles.py منطقُ تحميلٍ/تحقّقٍ عام — لا اسمَ دولةٍ/ISO/HS/جهةِ
    معايير فيه (تلك في ملفّات data/ حصراً). حارسٌ استباقيٌّ قبل بوّابة G5."""
    import re
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "silk_profiles.py"), encoding="utf-8").read()
    for token in ("QAT", "NLD", "NGA", "IND", "GCC", "NAFDAC", "FSSAI",
                  "200811", "080410"):
        assert token not in src, f"رمزٌ خاصٌّ بسوق/منتج تسرّب للمنطق: {token}"
    # لا رمزَ ISO3 لدولةٍ حقيقيةٍ أو خطَّ HS ٦ أرقام في المنطق.
    assert not re.search(r"\b\d{6}\b", src), "خطُّ HS في المنطق"
