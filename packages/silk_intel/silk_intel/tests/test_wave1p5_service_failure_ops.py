"""Wave 1.5 — عائلة «الفشل الصامت لخدمةٍ خارجية» (C): قفلٌ سلوكيّ.

فشلُ خدمةٍ خارجية **مُهيَّأة** يجب أن يترك أثرًا في `ops_errors` (نوع موحّد
`service_failure`) — لا يبتلعه `log.warning` وحده. هرمتي: الشبكة محجوبة
(`requests` مُرقَّعة)، وجدول ops على ملفٍ مؤقّت معزول.
"""
import contextlib
import os
import sys
import tempfile
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import silk_ops_log  # noqa: E402


@contextlib.contextmanager
def _ops_db():
    """جدول ops معزول على ملفٍ مؤقّت — يعيد مساره."""
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "ops.db")
        with mock.patch.object(silk_ops_log, "_db_path", lambda: path):
            yield path


def _service_failures(path):
    return [e for e in silk_ops_log.last_errors(50, path)
            if e["kind"] == "service_failure"]


def test_scraper_submit_failure_emits_service_ops_entry():
    """المكشطة مُهيَّأة (URL مضبوط) لكن POST يفشل => صفُّ service_failure
    باسم الخدمة scraper — لا فشلٌ صامت (بلاغ «المكشطة مضبوطة والهاتف —»)."""
    import silk_gmaps
    with _ops_db() as path, \
         mock.patch.dict(os.environ, {"SILK_GMAPS_SCRAPER_URL": "http://x.invalid"}), \
         mock.patch("requests.post",
                    side_effect=OSError("network disabled for offline test")):
        jid = silk_gmaps.submit_scrape(["مستوردو التمور هولندا"])
        fails = _service_failures(path)                 # اقرأ قبل تنظيف المجلّد
    assert jid is None                                  # تعطيل نظيف للعميل
    assert any(f["context"] and f["context"].get("service") == "scraper"
               for f in fails), f"لا سطر service_failure للـscraper: {fails}"


def test_configured_scraper_silent_no_op_is_now_visible():
    """جلبُ نتائج مهمةٍ يفشل شبكيًا => service_failure للـscraper (المرحلة fetch)."""
    import silk_gmaps
    with _ops_db() as path, \
         mock.patch.dict(os.environ, {"SILK_GMAPS_SCRAPER_URL": "http://x.invalid"}), \
         mock.patch("requests.get",
                    side_effect=OSError("network disabled for offline test")):
        status, results = silk_gmaps._fetch_job("job-123")
        fails = _service_failures(path)
    assert status is None and results is None
    assert any(f["context"] and f["context"].get("service") == "scraper"
               for f in fails)


def test_keyless_agent_failure_emits_service_ops_entry():
    """عيّنة وكيلٍ بلا مفتاح (Eurostat): فشلُ الجلب => service_failure."""
    import silk_eurostat_agent
    with _ops_db() as path, \
         mock.patch("requests.get",
                    side_effect=OSError("network disabled for offline test")):
        # دالّة الجلب المُدَقَّقة (`_fetch_jsonstat`) تمرّ عبر مسار الـexcept.
        with contextlib.suppress(Exception):
            silk_eurostat_agent._fetch_jsonstat("nrg_pc_204", {})
        fails = _service_failures(path)
    assert any(f["context"] and f["context"].get("service") == "eurostat"
               for f in fails)


def test_record_service_failure_uses_unified_kind():
    """الوسم الموحّد: كلُّ أعطال الخدمات نوعٌ واحدٌ (فرزٌ سهل للمشغّل)."""
    with _ops_db() as path:
        silk_ops_log.record_service_failure("comtrade", "429 rate limited")
        rows = silk_ops_log.last_errors(5, path)
    assert rows and rows[0]["kind"] == "service_failure"
    assert rows[0]["context"]["service"] == "comtrade"
    assert "[comtrade]" in rows[0]["reason"]
