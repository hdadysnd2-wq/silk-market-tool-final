"""اختبارات الموجة ٤هـ (V5): مراقبة ما بعد الدخول (silk_collectors).

يغطي: تحليلات غير "entered" أو بلا بحث عميق تُتجاهَل، نمو استيراد سلبي
يُطلق تنبيهاً، تغيّر التعريفة يُطلق تنبيهاً، فشل جلب تحليل واحد لا يوقف
البقية، ووجود المراقبة داخل refresh() على نفس خيط SILK_REFRESH_HOURS
(لا خدمة cron منفصلة). الشبكة مقطوعة عبر تمويه الدوال مباشرة (لا
block_network — الاختبارات تستدعي silk_storage الذي يفتح ملفات SQLite).
Run:  python3 -m pytest tests/ -q
"""
import os
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _fresh_db():
    import silk_storage
    db = os.path.join(tempfile.mkdtemp(), "silk.db")
    silk_storage.init_db(db)
    return db


def _save_entered(db, tariff_claim="التعريفة 5%", hs_code="080410"):
    import silk_storage
    result = {
        "product": "تمور", "hs_code": hs_code,
        "market": {"iso3": "NGA", "m49": "566"},
        "deep_research": {"missions": {"tariffs_agreements": {"findings": [
            {"note": "n", "value": tariff_claim}]}}},
    }
    aid = silk_storage.save_analysis(result, db)
    silk_storage.set_outcome(aid, "entered", db)
    return aid


def test_non_entered_and_non_deep_research_analyses_are_skipped():
    import silk_storage
    import silk_collectors as col

    db = _fresh_db()
    # تحليل كلاسيكي بلا deep_research (وإن كان "entered") — لا يُراقَب.
    classic_id = silk_storage.save_analysis(
        {"product": "أرز", "hs_code": "100630", "markets": []}, db)
    silk_storage.set_outcome(classic_id, "entered", db)
    # بحث عميق لكن بلا outcome=entered — لا يُراقَب أيضاً.
    silk_storage.save_analysis(
        {"product": "عسل", "hs_code": "040900",
         "market": {"iso3": "EGY", "m49": "818"},
         "deep_research": {"missions": {}}}, db)

    with patch("silk_storage._db_path", return_value=db), \
         patch("silk_data_layer.comtrade_trade") as fetch:
        alerts = col.check_post_entry()
    assert alerts == []
    fetch.assert_not_called()


def test_negative_growth_triggers_alert():
    import silk_collectors as col

    db = _fresh_db()
    _save_entered(db, tariff_claim="لا تعريفة مذكورة")

    def fake_comtrade(hs, market, year, flow="M", partner=0):
        return [{"primaryValue": 500.0}] if year == 2024 else \
               [{"primaryValue": 1000.0}]

    with patch("silk_storage._db_path", return_value=db), \
         patch("silk_data_layer.comtrade_trade", side_effect=fake_comtrade), \
         patch("silk_collectors._today_year", return_value=2025):
        alerts = col.check_post_entry()

    assert len(alerts) == 1
    assert alerts[0]["growth_negative"] is True


def test_tariff_change_triggers_alert():
    import silk_collectors as col
    from silk_data_layer import DataPoint

    db = _fresh_db()
    _save_entered(db, tariff_claim="التعريفة المطبقة على التمور 5%")

    with patch("silk_storage._db_path", return_value=db), \
         patch("silk_data_layer.comtrade_trade",
              return_value=[{"primaryValue": 1200.0}]), \
         patch("silk_tariffs_agent.applied_tariff",
              return_value=DataPoint(12.0, "World Bank WITS", 0.9, "n")):
        alerts = col.check_post_entry()

    assert len(alerts) == 1
    assert alerts[0]["tariff_changed"] is True
    assert alerts[0]["old_tariff_pct"] == 5.0
    assert alerts[0]["new_tariff_pct"] == 12.0


def test_no_material_change_produces_no_alert():
    import silk_collectors as col
    from silk_data_layer import DataPoint

    db = _fresh_db()
    _save_entered(db, tariff_claim="التعريفة 5%")

    with patch("silk_storage._db_path", return_value=db), \
         patch("silk_data_layer.comtrade_trade",
              return_value=[{"primaryValue": 1200.0}]), \
         patch("silk_tariffs_agent.applied_tariff",
              return_value=DataPoint(5.0, "World Bank WITS", 0.9, "n")):
        alerts = col.check_post_entry()
    assert alerts == []


def test_one_analysis_fetch_failure_does_not_block_others():
    import silk_storage
    import silk_collectors as col

    db = _fresh_db()
    _save_entered(db, hs_code="080410")  # aid=1 — سيفشل جلبه
    _save_entered(db, hs_code="090111")  # aid=2 — سينجح وينمو سلبياً

    def flaky_comtrade(hs, market, year, flow="M", partner=0):
        if hs == "080410":
            raise OSError("network disabled")
        return [{"primaryValue": 100.0}] if year == 2024 else \
               [{"primaryValue": 900.0}]

    with patch("silk_storage._db_path", return_value=db), \
         patch("silk_data_layer.comtrade_trade", side_effect=flaky_comtrade), \
         patch("silk_collectors._today_year", return_value=2025):
        alerts = col.check_post_entry()

    # التحليل الأول فشل جلبه (تجاهل معلوم)، الثاني اكتمل ونما سلبياً.
    assert len(alerts) == 1
    assert alerts[0]["analysis_id"] == 2


def test_refresh_runs_post_entry_monitoring_on_same_thread_no_separate_cron():
    import silk_collectors as col

    with patch("silk_collectors.collect_worldbank", return_value={}), \
         patch("silk_collectors._priority_targets", return_value=[]), \
         patch("silk_collectors._recent_hs_codes", return_value=[]), \
         patch("silk_collectors.comtrade_budget_left", return_value=999), \
         patch("silk_collectors.check_post_entry",
              return_value=[{"analysis_id": 1}]) as mocked, \
         patch("silk_store.migrate"):
        out = col.refresh()

    mocked.assert_called_once()
    assert out["post_entry_alerts"] == [{"analysis_id": 1}]


def test_refresh_survives_post_entry_monitoring_exception():
    import silk_collectors as col

    with patch("silk_collectors.collect_worldbank", return_value={}), \
         patch("silk_collectors._priority_targets", return_value=[]), \
         patch("silk_collectors._recent_hs_codes", return_value=[]), \
         patch("silk_collectors.comtrade_budget_left", return_value=999), \
         patch("silk_collectors.check_post_entry",
              side_effect=RuntimeError("boom")), \
         patch("silk_store.migrate"):
        out = col.refresh()  # لا يرمي استثناءً — طبقة مراقبة لا تُسقط التحديث

    assert out["post_entry_alerts"] == []
