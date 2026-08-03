"""اختبارات suggest_price (P1-6) — نطاق سعري موصى به من المرصود حصراً.

مواصفة المالك: compare_own_price تُموضِع ولا توصي — suggest_price يوصي
بنطاق مشتق من القوائم المرصودة (+ تكلفة/تعريفة المستخدم اختيارياً) بمعادلة
معلنة؛ بلا قوائم يعيد None بملاحظة — لا سعر مخترع أبداً.
Run:  python3 -m pytest tests/test_p1_suggest_price.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from silk_data_layer import DataPoint, _today  # noqa: E402
from silk_localprice_agent import suggest_price  # noqa: E402


def _listings(*prices: float) -> list[DataPoint]:
    return [DataPoint({"title": f"item{i}", "price": p, "currency": "USD"},
                      "Local retail", 0.8, "listing", _today())
            for i, p in enumerate(prices)]


def test_band_derived_from_observed_quartiles():
    out = suggest_price(_listings(10, 12, 14, 16, 20))
    b = out["basis"]
    assert b["listings_count"] == 5 and b["market_min"] == 10 \
        and b["market_max"] == 20
    # الربيع الأول → الوسيط: 12 → 14 (استيفاء خطي على 5 نقاط).
    assert out["suggested_min"] == 12 and out["suggested_max"] == 14
    assert "الوسيط" in out["rationale"] and "مرصود" in out["rationale"]
    assert out["landed_cost_floor"] is None      # بلا تكلفة => بلا أرضية


def test_cost_floor_raises_band_and_reports_margin():
    # تكلفة 10 + تعريفة 20% + شحن 1 => أرضية 13 — ترفع الحد الأدنى من 12.
    out = suggest_price(_listings(10, 12, 14, 16, 20),
                        cost_per_unit=10, tariff_pct=20, shipping_per_unit=1)
    assert out["landed_cost_floor"] == 13.0
    assert out["suggested_min"] == 13.0 and out["suggested_max"] == 14
    assert out["margin_at_min_pct"] == 0.0       # البيع عند الأرضية = صفر هامش
    assert out["margin_at_max_pct"] > 0
    assert "أرضية التكلفة" in out["rationale"]


def test_floor_above_all_observed_prices_declares_no_band():
    out = suggest_price(_listings(10, 12, 14), cost_per_unit=30)
    assert out["suggested_min"] is None and out["suggested_max"] is None
    assert out["landed_cost_floor"] == 30.0
    assert "لا نطاق ربحي" in out["note"]
    assert out["basis"]["listings_count"] == 3   # المرصود يبقى معلناً


def test_no_listings_returns_none_with_note_never_a_number():
    out = suggest_price([])
    assert out["suggested_min"] is None and out["suggested_max"] is None
    assert out["basis"] is None and "لا قوائم" in out["note"]
    # قوائم بلا أسعار صالحة = نفس الغياب المعلن.
    junk = [DataPoint({"title": "x", "price": "N/A"}, "Local retail", 0.5,
                      "bad", _today()),
            DataPoint(None, "Local retail", 0.0, "fetch failed", _today())]
    out2 = suggest_price(junk)
    assert out2["suggested_min"] is None and "لا قوائم" in out2["note"]
