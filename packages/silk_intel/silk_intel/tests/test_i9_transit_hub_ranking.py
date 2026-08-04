"""I9 — حارس مراكز إعادة التصدير في الترتيب.

المواصفة (I9) تُلزم بوسم مراكز إعادة التصدير (AE/NL/SG/HK/BE) وخصمِ نقاطها كي لا
يتصدّر هابٌ لوجستيّ قائمةَ الأسواق للمصدِّر السعودي بلا تحذير. هذا الحارس يقفل
السلوك على مستوى الدالة المساعدة (لا يحتاج شبكة) — لقطة الاختبار الهرمتية.

I9 — transit re-export hub guard in market ranking. Locks: the five named hubs
are recognised, each is tagged, its score is penalised, and a hub ranks below an
otherwise-equal non-hub.
"""

import silk_market_ranker as mr


def test_all_five_named_hubs_are_recognised():
    # المواصفة تسمّيها صراحةً — لا تُسقِط أياً منها.
    for iso3 in ("ARE", "NLD", "SGP", "HKG", "BEL"):
        assert iso3 in mr._TRANSIT_HUBS


def test_hub_is_tagged_and_penalised():
    adjusted, is_hub = mr._transit_hub_adjust("NLD", 0.80)
    assert is_hub is True
    # خصمٌ فعليّ مسقوف (0 < adjusted < original).
    assert adjusted < 0.80
    assert adjusted == round(0.80 * (1.0 - mr._TRANSIT_HUB_PENALTY), 4)


def test_non_hub_is_untouched_and_flagged_false():
    adjusted, is_hub = mr._transit_hub_adjust("DEU", 0.80)
    assert is_hub is False
    assert adjusted == 0.80


def test_hub_ranks_below_equal_non_hub():
    hub_score, _ = mr._transit_hub_adjust("SGP", 0.75)
    peer_score, is_hub = mr._transit_hub_adjust("DEU", 0.75)
    assert is_hub is False
    assert hub_score < peer_score
