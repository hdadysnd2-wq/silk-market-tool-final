"""درجة فرز المرحلة-١ — silk_market_ranker.stage1_screen_score (زيرو-شبكة).

Locked decision #8: the world funnel's Stage-1 screen scores each market by its
import volume modulated by the multi-year trend. This locks that contract —
growth lifts, decline lowers, the effect is bounded, a missing volume is a
declared gap (``0.0``, never fabricated — I1), and a missing trend leaves volume
unmodulated. Pure arithmetic; no network, no fixtures.
"""

from __future__ import annotations

import silk_market_ranker as mr


def test_flat_market_scores_its_volume():
    assert mr.stage1_screen_score(1000.0, cagr_3y=0.0) == 1000.0


def test_missing_trend_leaves_volume_unmodulated():
    assert mr.stage1_screen_score(1000.0) == 1000.0
    assert mr.stage1_screen_score(1000.0, cagr_3y=None, yoy_growth=None) == 1000.0


def test_growth_lifts_score_above_flat():
    assert mr.stage1_screen_score(1000.0, cagr_3y=0.2) > mr.stage1_screen_score(
        1000.0, cagr_3y=0.0
    )


def test_decline_lowers_score_below_flat():
    assert mr.stage1_screen_score(1000.0, cagr_3y=-0.2) < 1000.0


def test_cagr_is_preferred_over_yoy():
    # CAGR present → YoY ignored (3-yr trend is the steadier signal).
    assert mr.stage1_screen_score(1000.0, cagr_3y=0.1, yoy_growth=0.9) == 1000.0 * 1.1


def test_yoy_used_when_cagr_missing():
    assert mr.stage1_screen_score(1000.0, cagr_3y=None, yoy_growth=0.1) == 1000.0 * 1.1


def test_trend_effect_is_bounded():
    cap = mr.STAGE1_GROWTH_CAP
    assert mr.stage1_screen_score(1000.0, cagr_3y=99.0) == 1000.0 * (1.0 + cap)
    assert mr.stage1_screen_score(1000.0, cagr_3y=-99.0) == 1000.0 * (1.0 - cap)


def test_missing_volume_is_declared_gap_not_fabricated():
    # I1 — no volume → 0.0, never a value invented from the trend.
    assert mr.stage1_screen_score(None, cagr_3y=0.5) == 0.0
    assert mr.stage1_screen_score(None) == 0.0
