"""اختبارات P2-8c/8d — النطاق غير النفطي + الأسواق الديناميكية.

يقفل: (١) فصل HS 27 (وقود معدنية) خارج نطاق سِلك برسالة عربية واضحة عبر
نقطة حقيقة واحدة (exclusion_note) تخدم المصنّف ومسار hs_code الصريح
والاكتشاف العكسي؛ (٢) أكبر المستوردين عالمياً يُشتقون من كومتريد
ديناميكياً مع تراجع معلن للقائمة المنسّقة عند الغياب — لا انحدار هرمتي.
Run:  python3 -m pytest tests/test_p2_scope_and_dynamic_markets.py -q
"""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conftest import block_network  # noqa: E402


# ── (١) بوابة النطاق غير النفطي — HS chapter 27 ─────────────────────────────

def test_exclusion_note_single_source_of_truth():
    from silk_hs_resolver import EXCLUDED_HS_CHAPTERS, exclusion_note
    assert "27" in EXCLUDED_HS_CHAPTERS
    for code in ("270900", "271012", "271600", "27"):
        note = exclusion_note(code)
        assert note and "غير النفطي" in note and "بترولي" in note
    for code in ("080410", "040900", "570110", None, ""):
        assert exclusion_note(code) is None


def test_engine_explicit_petroleum_hs_declared_out_of_scope():
    import silk_engine
    with block_network():
        res = silk_engine.analyze("نفط خام", hs_code="270900",
                                  countries=[{"iso3": "CHN", "m49": "156"}])
    assert res["classified"] is False and res["hs_code"] is None
    assert "غير النفطي" in res["hs_note"]
    assert res["markets"] == []                     # لا تحليل لمنتج مستبعد


def test_resolver_strong_petroleum_match_returns_none_with_reason():
    import csv
    import tempfile
    from silk_hs_resolver import resolve
    path = os.path.join(tempfile.mkdtemp(), "seed.csv")
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["hs_code", "name_en", "name_ar",
                                          "keywords"])
        w.writeheader()
        w.writerow({"hs_code": "270900", "name_en": "crude oil",
                    "name_ar": "نفط خام", "keywords": "نفط,crude,oil"})
        w.writerow({"hs_code": "040900", "name_en": "natural honey",
                    "name_ar": "عسل طبيعي", "keywords": "عسل,honey"})
    dp = resolve("نفط خام", path=path)
    assert dp.value is None and "غير النفطي" in dp.note
    dp2 = resolve("عسل طبيعي", path=path)          # غير المستبعد يمرّ طبيعياً
    assert dp2.value == "040900"


def test_discovery_totals_skip_excluded_chapters():
    from silk_discovery import _totals_by_hs
    recs = [{"cmdCode": "270900", "primaryValue": 9.9e9},
            {"cmdCode": "080410", "primaryValue": 5.0e6}]
    totals = _totals_by_hs(recs)
    assert "270900" not in totals and totals["080410"] == 5.0e6


# ── (٢) الأسواق الديناميكية — top importers from Comtrade ───────────────────

_ROWS = [
    {"reporterCode": "156", "reporterISO": "CHN", "primaryValue": 9.0e7},
    {"reporterCode": "784", "reporterISO": "ARE", "primaryValue": 7.0e7},
    {"reporterCode": "682", "reporterISO": "SAU", "primaryValue": 6.0e7},
    {"reporterCode": "999", "primaryValue": 5.0e7},        # بلا iso3 => يُسقط
    {"reporterCode": "356", "reporterISO": "IND", "primaryValue": None},
    {"reporterCode": "276", "reporterISO": "DEU", "primaryValue": 4.0e7},
]


def test_top_import_markets_sorted_mapped_and_saudi_excluded():
    import silk_market_ranker as R
    with mock.patch.object(R, "top_import_markets",
                           wraps=R.top_import_markets):
        with mock.patch("silk_data_layer.comtrade_trade",
                        return_value=list(_ROWS)) as ct:
            got = R.top_import_markets("040900", 2024, n=10)
    assert ct.call_args.args[1] is None            # reporter=all (محذوف)
    isos = [g["iso3"] for g in got]
    assert isos == ["CHN", "ARE", "DEU"]           # مرتبة تنازلياً بالقيمة
    assert "SAU" not in isos                       # المنشأ ليس سوقاً مستهدفاً
    assert all(g["m49"] for g in got)


def test_rank_markets_falls_back_to_curated_list_offline():
    import silk_market_ranker as R
    with block_network():
        rows = R.rank_markets("040900", countries=None, year=2023)
    # كومتريد غائب => التراجع المعلن للقائمة المنسّقة — كل الأسواق الـ38.
    assert len(rows) == len(R.COUNTRIES)


def test_dynamic_markets_owner_kill_switch():
    import silk_market_ranker as R
    with mock.patch.dict(os.environ, {"SILK_DYNAMIC_MARKETS": "0"}):
        with mock.patch("silk_data_layer.comtrade_trade") as ct:
            with block_network():
                R.rank_markets("040900", countries=None, year=2023)
    # الصمام مقفل => لا محاولة ديناميكية إطلاقاً (كومتريد لا يُستدعى للترشيح).
    assert not any(call.args[1] is None for call in ct.call_args_list)
