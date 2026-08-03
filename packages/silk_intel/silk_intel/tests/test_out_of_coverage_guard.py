"""قفل بوّابة «خارج التغطية» (الميزة أ · اتفاق المالك) — out-of-coverage guard.

العائلة المحروسة: **out-of-coverage-thin-study** — أن يُشغَّل بحثٌ عميق هزيل
لسوقٍ لا يستورد هذا الرمز فعلاً (ليس Tier-1 ولا ضمن Tier-2 الديناميكية). العقد:
مع تفعيل تغطية العالم، سوقٌ خارج التغطية => رسالة صادقة «هذه السوق خارج التغطية
الحالية — تواصل معنا لإضافتها» (٤٢٢، تُسطَّح للواجهة) + تسجيل الطلب إشارةَ طلبٍ
في سجلّ العمليات — لا دراسةٌ هزيلة. الصمّام مُطفأ => السلوك كاليوم بلا انحدار.
"""
from __future__ import annotations

import importlib
import os
import sys
import tempfile
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402
import silk_market_ranker as R  # noqa: E402
import silk_ops_log  # noqa: E402

_MSG = "هذه السوق خارج التغطية الحالية — تواصل معنا لإضافتها"


def _client(**env):
    import api as api_mod
    for k, v in env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    importlib.reload(api_mod)
    return TestClient(api_mod.create_app())


def _totals(*iso3s):
    return [{"iso3": i, "m49": "999", "total_usd": 1000.0} for i in iso3s]


def test_out_of_coverage_market_returns_honest_message_and_logs_demand():
    """ABW (أروبا، ليست Tier-1) وليست ضمن مستوردي الرمز => ٤٢٢ + الرسالة
    الصادقة + تسجيل الطلب إشارةَ طلبٍ في سجلّ العمليات — لا تشغيل دراسة."""
    ops_db = os.path.join(tempfile.mkdtemp(), "ops.db")
    with mock.patch.object(R, "world_import_totals",
                           return_value=_totals("USA", "DEU", "CHN")):
        client = _client(SILK_WORLD_MARKETS="1", SILK_API_KEY=None,
                         SILK_OPS_LOG_DB=ops_db)
        with mock.patch("requests.get",
                        side_effect=OSError("net blocked for offline test")):
            r = client.post("/research",
                            json={"product": "تمر", "market": "Aruba",
                                  "hs_code": "080410", "async_run": False,
                                  "persist": False})
    assert r.status_code == 422
    d = r.json()["detail"]
    assert d["error"] == "out_of_coverage" and d["message"] == _MSG
    # سُجّل إشارةَ طلبٍ (demand signal) لا خطأً صامتاً
    logged = silk_ops_log.last_errors(10, path=ops_db)
    assert any(e["kind"] == "out_of_coverage_demand" for e in logged), logged
    try:
        del os.environ["SILK_WORLD_MARKETS"]; del os.environ["SILK_OPS_LOG_DB"]
    finally:
        importlib.reload(__import__("api"))


def test_tier2_real_importer_is_covered_not_blocked():
    """ABW ضمن مجموعة أكبر مستوردي الرمز => لا حجب تغطية (يمرّ للجهوزية)."""
    with mock.patch.object(R, "world_import_totals",
                           return_value=_totals("USA", "DEU", "ABW", "CHN")):
        client = _client(SILK_WORLD_MARKETS="1", SILK_API_KEY=None)
        with mock.patch("requests.get",
                        side_effect=OSError("net blocked for offline test")):
            r = client.post("/research",
                            json={"product": "تمر", "market": "Aruba",
                                  "hs_code": "080410", "async_run": False,
                                  "persist": False})
    # ليست ٤٢٢-خارج-تغطية (تمرّ البوّابة ثم تصطدم بالجهوزية ٤٠٩ بلا مفتاح)
    assert not (r.status_code == 422
                and r.json().get("detail", {}).get("error") == "out_of_coverage")
    try:
        del os.environ["SILK_WORLD_MARKETS"]
    finally:
        importlib.reload(__import__("api"))


def test_tier1_curated_market_is_always_covered():
    """سوق منسّق (الإمارات ARE) لا يُحجَب أبداً — لا نداء عالمٍ حتى (Tier-1)."""
    probe = mock.Mock(side_effect=AssertionError(
        "Tier-1 يجب ألّا يستدعي نداء العالم"))
    with mock.patch.object(R, "world_import_totals", probe):
        client = _client(SILK_WORLD_MARKETS="1", SILK_API_KEY=None)
        with mock.patch("requests.get",
                        side_effect=OSError("net blocked for offline test")):
            r = client.post("/research",
                            json={"product": "تمر", "market": "ARE",
                                  "hs_code": "080410", "async_run": False,
                                  "persist": False})
    assert not (r.status_code == 422
                and r.json().get("detail", {}).get("error") == "out_of_coverage")
    probe.assert_not_called()
    try:
        del os.environ["SILK_WORLD_MARKETS"]
    finally:
        importlib.reload(__import__("api"))


def test_flag_off_no_coverage_guard_any_country_works_todays_way():
    """الصمّام مُطفأ => لا بوّابة تغطية إطلاقاً (السلوك كاليوم، فجوات معلنة) —
    أروبا تمرّ للجهوزية بلا رسالة «خارج التغطية»."""
    probe = mock.Mock(side_effect=AssertionError(
        "الصمّام مُطفأ يجب ألّا يستدعي نداء العالم"))
    with mock.patch.object(R, "world_import_totals", probe):
        client = _client(SILK_WORLD_MARKETS=None, SILK_API_KEY=None)
        with mock.patch("requests.get",
                        side_effect=OSError("net blocked for offline test")):
            r = client.post("/research",
                            json={"product": "تمر", "market": "Aruba",
                                  "hs_code": "080410", "async_run": False,
                                  "persist": False})
    assert not (r.status_code == 422
                and r.json().get("detail", {}).get("error") == "out_of_coverage")
    probe.assert_not_called()
    importlib.reload(__import__("api"))


def test_undeterminable_coverage_fails_open(monkeypatch):
    """تعذّر تحديد المجموعة (نداء العالم فارغ: ميزانية/شبكة) => فتح البوّابة
    (سوق مشروع لا يُحجَب على عطلٍ عابر) — لا ٤٢٢ خارج تغطية."""
    with mock.patch.object(R, "world_import_totals", return_value=[]):
        client = _client(SILK_WORLD_MARKETS="1", SILK_API_KEY=None)
        with mock.patch("requests.get",
                        side_effect=OSError("net blocked for offline test")):
            r = client.post("/research",
                            json={"product": "تمر", "market": "Aruba",
                                  "hs_code": "080410", "async_run": False,
                                  "persist": False})
    assert not (r.status_code == 422
                and r.json().get("detail", {}).get("error") == "out_of_coverage")
    try:
        del os.environ["SILK_WORLD_MARKETS"]
    finally:
        importlib.reload(__import__("api"))


# ── تدقيق v2، الموجة ١ (HIGH #1/#2): البوّابة تُغلق فعلاً عبر سُلَّم fallback ──

def test_world_import_totals_resolved_ladders_to_first_nonempty_year():
    """المُحَلِّل يبدأ من سنة اليوم-١ ويتدرّج حتى أوّل سنةٍ غير فارغة (سنة الدراسة
    الافتراضية) — لا يقف عند سنةٍ فارغة (الخلل الأصلي: استطلاعٌ لسنةٍ واحدة)."""
    import datetime as _dt
    from silk_market_ranker import DEFAULT_STUDY_YEAR
    calls: list[int] = []

    def _by_year(hs, year):
        calls.append(year)
        return _totals("USA", "DEU", "CHN") if year == DEFAULT_STUDY_YEAR else []

    with mock.patch.object(R, "world_import_totals", side_effect=_by_year):
        totals, yr = R.world_import_totals_resolved("080410")
    assert yr == DEFAULT_STUDY_YEAR and totals, (yr, totals)
    assert calls[0] == _dt.date.today().year - 1, "لم يبدأ من سنة اليوم-١"
    assert DEFAULT_STUDY_YEAR in calls, "لم يتدرّج حتى سنة الدراسة"


def test_coverage_gate_closes_when_current_year_empty_but_study_year_full():
    """اللقطة الحرفية للخلل (HIGH #1): سنة اليوم-١ (٢٠٢٥) فارغة — كومتريد متأخّر —
    بينما سنة الدراسة (٢٠٢٢) ممتلئة. قبل الإصلاح: البوّابة تستطلع ٢٠٢٥ وحدها،
    تعود فارغة، فتفشل مفتوحةً (أيّ سوق يمرّ). بعده: السُّلَّم يتدرّج حتى ٢٠٢٢
    فتُغلَق البوّابة فعلاً على سوقٍ خارج أكبر مئة مستورد (ABW) => ٤٢٢."""
    from silk_market_ranker import DEFAULT_STUDY_YEAR
    ops_db = os.path.join(tempfile.mkdtemp(), "ops.db")

    def _by_year(hs, year):
        # ٢٠٢٢ وحدها ممتلئة؛ ABW غائبة عنها => خارج التغطية.
        return _totals("USA", "DEU", "CHN") if year == DEFAULT_STUDY_YEAR else []

    with mock.patch.object(R, "world_import_totals", side_effect=_by_year):
        client = _client(SILK_WORLD_MARKETS="1", SILK_API_KEY=None,
                         SILK_OPS_LOG_DB=ops_db)
        with mock.patch("requests.get",
                        side_effect=OSError("net blocked for offline test")):
            r = client.post("/research",
                            json={"product": "تمر", "market": "Aruba",
                                  "hs_code": "080410", "async_run": False,
                                  "persist": False})
    assert r.status_code == 422, r.text
    d = r.json()["detail"]
    assert d["error"] == "out_of_coverage" and d["message"] == _MSG
    try:
        del os.environ["SILK_WORLD_MARKETS"]; del os.environ["SILK_OPS_LOG_DB"]
    finally:
        importlib.reload(__import__("api"))
