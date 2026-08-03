"""اختبارات التحديث المُجدول — scheduled refresh & pre-warm (silk_collectors).

يقفل: (١) أسواق الأولوية من البيئة أو أول قائمة المنصّة، ورموز مجهولة تُسقَط
(لا اختلاق سوق)؛ (٢) رموز HS الأخيرة تُقرأ من سجل التحليلات بالأحدث أولاً بلا
تكرار؛ (٣) refresh يسخّن رموز HS الأخيرة × أسواق الأولوية للسنة المغلقة
الأخيرة عبر collect_comtrade نفسه (الميزانية/الإيقاع/backoff القائمة) ويحترم
احتياطي الميزانية للطلبات الحية؛ (٤) المُجدول معطّل بنيوياً بلا
SILK_REFRESH_HOURS — لا خيط إطلاقاً.
"""
import datetime
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import silk_collectors  # noqa: E402


def test_priority_targets_env_override_drops_unknown(monkeypatch):
    monkeypatch.setenv("SILK_PRIORITY_MARKETS", "are, kwt ,XXX")
    got = silk_collectors._priority_targets()
    assert [t["iso3"] for t in got] == ["ARE", "KWT"]   # XXX أُسقط — لا اختلاق
    assert all(t["m49"] for t in got)


def test_priority_targets_default_is_platform_head(monkeypatch):
    monkeypatch.delenv("SILK_PRIORITY_MARKETS", raising=False)
    from silk_market_ranker import COUNTRIES
    got = silk_collectors._priority_targets()
    assert got == COUNTRIES[:12]


def test_recent_hs_codes_newest_first_dedup(monkeypatch, tmp_path):
    monkeypatch.setenv("SILK_DB", str(tmp_path / "silk.db"))
    import silk_storage
    for hs in ("040900", "080410", "040900", "090111"):
        silk_storage.save_analysis({"product": "x", "hs_code": hs,
                                    "year": 2023, "markets": []})
    got = silk_collectors._recent_hs_codes(limit=2)
    assert got == ["090111", "040900"]                  # الأحدث أولاً، بلا تكرار


def test_recent_hs_codes_empty_on_missing_db(monkeypatch, tmp_path):
    monkeypatch.setenv("SILK_DB", str(tmp_path / "absent.db"))
    assert silk_collectors._recent_hs_codes() == []


def test_refresh_prewarms_recent_hs_across_priority_markets(monkeypatch,
                                                            tmp_path):
    monkeypatch.setenv("SILK_DB", str(tmp_path / "silk.db"))
    monkeypatch.setenv("SILK_PRIORITY_MARKETS", "ARE,KWT")
    import silk_storage
    for hs in ("040900", "080410"):
        silk_storage.save_analysis({"product": "x", "hs_code": hs,
                                    "year": 2023, "markets": []})
    calls = []
    with mock.patch.object(silk_collectors, "collect_worldbank",
                           return_value={"fetched": 7, "failed": 0,
                                         "seeded": 0}), \
         mock.patch.object(silk_collectors, "collect_comtrade",
                           side_effect=lambda hs6, targets, year:
                           calls.append((hs6, tuple(t["iso3"] for t in targets),
                                         year)) or
                           {"requested": len(targets), "fetched": len(targets),
                            "failed": 0, "skipped_budget": 0,
                            "budget_left": 400}), \
         mock.patch.object(silk_collectors, "comtrade_budget_left",
                           return_value=400):
        got = silk_collectors.refresh()
    closed_year = datetime.date.today().year - 1
    assert [c[0] for c in calls] == ["080410", "040900"]   # الأحدث أولاً
    assert all(c[1] == ("ARE", "KWT") and c[2] == closed_year for c in calls)
    assert len(got["comtrade"]) == 2
    assert got["worldbank"]["fetched"] == 7


def test_refresh_respects_live_traffic_budget_reserve(monkeypatch, tmp_path):
    monkeypatch.setenv("SILK_DB", str(tmp_path / "silk.db"))
    import silk_storage
    silk_storage.save_analysis({"product": "x", "hs_code": "040900",
                                "year": 2023, "markets": []})
    with mock.patch.object(silk_collectors, "collect_worldbank",
                           return_value={"fetched": 0, "failed": 0,
                                         "seeded": 0}), \
         mock.patch.object(silk_collectors, "collect_comtrade") as cc, \
         mock.patch.object(silk_collectors, "comtrade_budget_left",
                           return_value=150):   # == الاحتياطي الافتراضي
        got = silk_collectors.refresh()
    cc.assert_not_called()                      # التسخين لا يجوّع الطلبات الحية
    assert got["comtrade"] == []


def test_scheduler_off_without_env_and_idempotent(monkeypatch):
    monkeypatch.delenv("SILK_REFRESH_HOURS", raising=False)
    monkeypatch.setattr(silk_collectors, "_scheduler_started", False)
    assert silk_collectors.start_scheduler() is None     # معطّل بنيوياً

    monkeypatch.setenv("SILK_REFRESH_HOURS", "24")
    monkeypatch.setenv("SILK_REFRESH_INITIAL_S", "9999999")  # لن تعمل تشغيلة
    t = silk_collectors.start_scheduler()
    assert t is not None and t.daemon and t.is_alive()
    assert silk_collectors.start_scheduler() is None     # لا خيط ثانٍ
    monkeypatch.setattr(silk_collectors, "_scheduler_started", False)


def test_scheduler_rejects_garbage_hours(monkeypatch):
    monkeypatch.setenv("SILK_REFRESH_HOURS", "daily")
    monkeypatch.setattr(silk_collectors, "_scheduler_started", False)
    assert silk_collectors.start_scheduler() is None
