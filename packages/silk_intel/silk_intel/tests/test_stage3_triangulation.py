"""اختبارات التثليث (Stage 3 توسعة) — إحصاءات المرآة بين تقريرَين مستقلَّين.

يقفل: `_triangulate` نقيّة (اتفاق/تباين/مصدر واحد/غياب مزدوج، لا اختلاق قيمة
موحّدة أبداً)؛ `mirror_saudi_export` يستدعي كومتريد بـ reporter=SAU
flow=X فعلاً؛ CompetitorAgent وPricingAgent يثلّثان saudi_share_pct
وsaudi_border_unit_value_usd_kg بمصدرين عند توفّر المرآة، ويتراجعان بأمان
لمصدر واحد أو فجوة عند غيابها — أثبتَ سيناريو «فجوة بيانات رسمية حقيقية»:
غياب السعودية عن تقرير الجهة المستوردة يُستدرَك بالمرآة.
"""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conftest import block_network  # noqa: E402

import silk_research as R  # noqa: E402
import silk_store  # noqa: E402
from silk_data_layer import DataPoint, _today  # noqa: E402


def _dp(v, src="UN Comtrade", conf=0.9, note=""):
    return DataPoint(v, src, conf, note, _today())


# ── _triangulate: الدالة النقية ───────────────────────────────────────────────

def test_triangulate_both_absent_is_a_declared_gap():
    tri = R._triangulate(None, None)
    assert tri == {"value": None, "sources": [], "note": "",
                   "divergence_pct": None}


def test_triangulate_only_primary_single_source_flagged_untriangulated():
    tri = R._triangulate(_dp(30.0), None)
    assert tri["value"] == 30.0
    assert len(tri["sources"]) == 1
    assert "غير مثلَّث" in tri["note"] and tri["divergence_pct"] is None


def test_triangulate_only_mirror_single_source_uses_mirror_value():
    tri = R._triangulate(None, _dp(28.5, src="UN Comtrade (تقرير سعودي مباشر — مرآة)"))
    assert tri["value"] == 28.5
    assert len(tri["sources"]) == 1
    assert "غير مثلَّث" in tri["note"]
    assert "مرآة" in tri["note"]


def test_triangulate_agreement_keeps_primary_value_dual_source_no_confidence_hit():
    primary, mirror = _dp(30.0, conf=0.9), _dp(31.0, conf=0.9)
    tri = R._triangulate(primary, mirror, threshold_pct=20.0)
    assert tri["value"] == 30.0                    # الأساسية دوماً — لا دمج مخترع
    assert len(tri["sources"]) == 2
    assert tri["divergence_pct"] < 20.0 and tri["agree"] is True
    assert "مثلَّث" in tri["note"] and "تباين تثليث" not in tri["note"]
    assert tri["sources"][0]["confidence"] == 0.9   # اتفاق: لا تخفيض ثقة


def test_triangulate_divergence_flags_and_discounts_confidence_never_fabricates_merge():
    primary, mirror = _dp(30.0, conf=0.9), _dp(60.0, conf=0.9)  # تباين 50%
    tri = R._triangulate(primary, mirror, threshold_pct=20.0)
    assert tri["value"] == 30.0                    # ليس 45 (المتوسط) — لا اختلاق
    assert tri["agree"] is False and tri["divergence_pct"] == 50.0
    assert "تباين تثليث" in tri["note"] and "معلن" in tri["note"]
    assert len(tri["sources"]) == 2
    assert tri["sources"][0]["confidence"] == 0.6   # خُفِّضت لا حُذفت


# ── mirror_saudi_export: نداء كومتريد الفعلي (reporter=SAU, flow=X) ──────────

def test_mirror_saudi_export_calls_comtrade_with_reporter_sau_flow_x():
    import silk_data_layer_v2 as v2
    calls = []

    def fake_comtrade(hs, reporter, year, flow="M", partner=0):
        calls.append((hs, str(reporter), year, flow, partner))
        return [{"primaryValue": 1.9e7, "netWgt": 8.5e6}]

    with mock.patch.object(v2, "comtrade_trade", fake_comtrade):
        dp = v2.mirror_saudi_export("080410", "156", "CHN", 2023)
    assert calls == [("080410", "682", 2023, "X", "156")]
    assert dp.value == {"value_usd": 1.9e7, "qty_kg": 8.5e6}
    assert "مرآة" in dp.source


def test_mirror_saudi_export_no_data_is_declared_none_not_zero():
    import silk_data_layer_v2 as v2
    with mock.patch.object(v2, "comtrade_trade", return_value=[]):
        dp = v2.mirror_saudi_export("080410", "156", "CHN", 2023)
    assert dp.value is None and dp.confidence == 0.0
    assert "غير متاحة" in dp.note


# ── التكامل: CompetitorAgent وPricingAgent يثلّثان الحقائق السعودية ──────────

def _seed_store(sau_row=True):
    silk_store.migrate()
    rows = [{"hs6": "080410", "reporter_iso3": "CHN", "partner_iso3": "WLD",
             "year": 2023, "flow": "M", "value_usd": 6.0e7, "qty_kg": 2.0e7},
            {"hs6": "080410", "reporter_iso3": "CHN", "partner_iso3": "IRN",
             "year": 2023, "flow": "M", "value_usd": 3.0e7},
            {"hs6": "080410", "reporter_iso3": "CHN", "partner_iso3": "TUN",
             "year": 2023, "flow": "M", "value_usd": 1.2e7}]
    if sau_row:
        rows.append({"hs6": "080410", "reporter_iso3": "CHN",
                     "partner_iso3": "SAU", "year": 2023, "flow": "M",
                     "value_usd": 1.8e7, "qty_kg": 8.0e6})
    silk_store.upsert_trade_flows(rows)


TASK = {"product": "تمور", "hs6": "080410", "iso3": "CHN", "m49": "156",
        "iso2": "CN", "market_name": "China", "year": 2023}


def test_competitor_agent_triangulates_saudi_share_with_agreeing_mirror():
    _seed_store(sau_row=True)   # target-reported: SAU share = 30.0%
    mirror = _dp({"value_usd": 1.9e7, "qty_kg": 8.5e6},
                 src="UN Comtrade (تقرير سعودي مباشر — مرآة)")
    with block_network(), \
         mock.patch("silk_data_layer_v2.mirror_saudi_export",
                   return_value=mirror):
        out = R.CompetitorAgent().run(dict(TASK)).findings[0]
    f = next(x for x in out["findings"] if x["metric"] == "saudi_share_pct")
    assert f["value"] == 30.0                       # الأساسية (الجهة المستوردة)
    assert len(f["sources"]) == 2                    # كلا التقريرين ظاهران
    assert "مثلَّث" in f["note"]


def test_competitor_agent_recovers_saudi_share_via_mirror_when_absent_from_target_report():
    """السيناريو المطلوب إثباته: فجوة بيانات رسمية حقيقية — السعودية غائبة عن
    تقرير الجهة المستوردة (حالة شائعة: تصنيف شريك مختلف/عتبة إبلاغ) لكن
    التقرير السعودي المباشر يثبت التجارة — التثليث يستدرك الفجوة بصدق."""
    _seed_store(sau_row=False)  # السعودية غير ظاهرة في تقرير الجهة المستوردة
    mirror = _dp({"value_usd": 1.9e7, "qty_kg": 8.5e6},
                 src="UN Comtrade (تقرير سعودي مباشر — مرآة)")
    with block_network(), \
         mock.patch("silk_data_layer_v2.mirror_saudi_export",
                   return_value=mirror):
        out = R.CompetitorAgent().run(dict(TASK)).findings[0]
    f = next(x for x in out["findings"] if x["metric"] == "saudi_share_pct")
    # grand = 3.0e7 + 1.2e7 = 4.2e7؛ مرآة = 1.9e7/4.2e7*100 ≈ 45.24%
    assert f["value"] == round(100 * 1.9e7 / 4.2e7, 2)
    assert len(f["sources"]) == 1
    assert "التقرير السعودي المباشر" in f["note"]


def test_competitor_agent_double_absence_is_declared_gap_not_fabricated_zero():
    _seed_store(sau_row=False)
    no_mirror = _dp(None, src="UN Comtrade (تقرير سعودي مباشر — مرآة)")
    with block_network(), \
         mock.patch("silk_data_layer_v2.mirror_saudi_export",
                   return_value=no_mirror):
        out = R.CompetitorAgent().run(dict(TASK)).findings[0]
    metrics = [x["metric"] for x in out["findings"] if x["value"] is not None]
    assert "saudi_share_pct" not in metrics
    assert any("saudi_share_pct" in g and "غياب مزدوج" in g
              for g in out["gaps"])


def test_pricing_agent_triangulates_saudi_unit_value_with_diverging_mirror():
    _seed_store(sau_row=True)   # target-reported unit value = 1.8e7/8.0e6 = 2.25
    mirror = _dp({"value_usd": 4.0e7, "qty_kg": 8.0e6},   # وحدة 5.0 — تباين كبير
                 src="UN Comtrade (تقرير سعودي مباشر — مرآة)")
    with block_network(), \
         mock.patch("silk_data_layer_v2.mirror_saudi_export",
                   return_value=mirror), \
         mock.patch.dict(os.environ, {"SEARCH_API_KEY": ""}):
        out = R.PricingAgent().run(dict(TASK)).findings[0]
    f = next(x for x in out["findings"]
            if x["metric"] == "saudi_border_unit_value_usd_kg")
    assert f["value"] == 2.25                        # الأساسية — لا متوسط مخترع
    assert len(f["sources"]) == 2
    assert "تباين تثليث" in f["note"]
    assert f["modeled"] is True and f["formula"]


def test_triangulation_disclosure_visible_in_rendered_report_not_just_agent_output():
    """المصداقية تنتهي عند التقرير المسلَّم لا عند مخرجات الوكيل — الاتفاق أو
    التباين يجب أن يظهر فعلياً في نص Markdown/Word المُصدَّر، لا فقط في dict
    داخلي لا يراه المراجع."""
    _seed_store(sau_row=False)
    mirror = _dp({"value_usd": 1.9e7, "qty_kg": 8.5e6},
                 src="UN Comtrade (تقرير سعودي مباشر — مرآة)")
    import silk_engine
    from silk_render import build_view
    from silk_reports import render_markdown
    with block_network(), \
         mock.patch("silk_data_layer_v2.mirror_saudi_export",
                   return_value=mirror):
        res = silk_engine.analyze("تمور",
                                  countries=[{"iso3": "CHN", "m49": "156"}],
                                  year=2023, with_research=True)
    md = render_markdown(build_view(res))
    assert "التقرير السعودي المباشر" in md   # إفصاح التثليث ظاهر في التقرير
