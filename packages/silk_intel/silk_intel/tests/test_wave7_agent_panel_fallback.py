"""اختبارات: لوحة إعدادات الوكلاء والبعثات الاثنتا عشرة (الموجة ٧).

بلاغ: "اللوحة تعرض الوكلاء القدامى فقط". يغطي: التسجيل الخادمي الصحيح
(AGENT_CATALOG + GET /settings/agents يعيدان الـ٢٨ صفاً)، والسبب الجذري
الفعلي — سقوط صامت للوحة على قائمة احتياطية (١٤ قديماً) حين يرفض الخادم
GET /settings/agents بـ401 (نشر محمي بـSILK_API_KEY قبل ضبط مفتاح الخدمة
في المتصفح) — وإصلاحه: تحذير مرئي بدل سقوط صامت.
Run:  python3 -m pytest tests/test_wave7_agent_panel_fallback.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_MISSION_KEYS = (
    "pricing_scout", "consumer_culture", "trade_flow", "demographics_economy",
    "competitors", "customs_requirements", "tariffs_agreements", "logistics",
    "channels_importers", "demand_trends", "risk_news", "opportunity_gaps",
)


def _client():
    from fastapi.testclient import TestClient
    import api
    return TestClient(api.app)


def test_all_12_mission_agents_registered_in_catalog_with_role_lines():
    import silk_missions  # noqa: F401 — يسجّل صفوف البعثات عند الاستيراد
    from silk_agents import AGENT_CATALOG

    catalog = {a["key"]: a for a in AGENT_CATALOG}
    missing = [k for k in _MISSION_KEYS if k not in catalog]
    assert not missing, f"missing mission agents in AGENT_CATALOG: {missing}"
    for k in _MISSION_KEYS:
        row = catalog[k]
        assert row.get("name"), f"{k} has no display name"
        assert row.get("role"), f"{k} has no role line"


def test_reviewer_and_report_writer_also_registered():
    import silk_ai_judge  # noqa: F401 — يسجّل reviewer/report_writer
    from silk_agents import AGENT_CATALOG
    catalog = {a["key"] for a in AGENT_CATALOG}
    assert {"reviewer", "report_writer"} <= catalog


def test_settings_endpoint_returns_all_agents_including_missions():
    r = _client().get("/settings/agents")
    assert r.status_code == 200
    keys = {a["key"] for a in r.json()["agents"]}
    missing = [k for k in _MISSION_KEYS if k not in keys]
    assert not missing, f"missing from GET /settings/agents: {missing}"
    assert {"reviewer", "report_writer"} <= keys
    # لا تصادم مع الوكلاء الأربعة عشر القدامى — تسجيل إضافي لا استبدال.
    assert len(keys) >= 14 + 12 + 2


def test_settings_endpoint_401s_when_protected_and_unauthenticated():
    # السبب الجذري: هذا بالضبط ما يجعل اللوحة تسقط على القائمة الاحتياطية
    # القديمة صامتة لو لم يُصلَح fetch الواجهة (web/index.html).
    from unittest.mock import patch
    with patch.dict(os.environ, {"SILK_API_KEY": "secret"}):
        r = _client().get("/settings/agents")
    assert r.status_code == 401


_HTML = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "web", "index.html")


def _html() -> str:
    return open(_HTML, encoding="utf-8").read()


def test_web_panel_no_longer_swallows_a_failed_catalog_fetch_silently():
    html = _html()
    # الإصلاح: حالة صريحة (catalogStatus) بدل catch فارغ يُبقي AGENTS
    # الاحتياطية للأبد بلا أي أثر مرئي للمستخدم.
    assert "S.catalogStatus" in html
    assert "err.status" in html or "e.status" in html
    assert "unauthorized" in html
    # تحذير مرئي فعلي في الدرج، لا سقوط صامت.
    assert "قائمة احتياطية" in html


def test_web_panel_maps_server_role_field_into_displayed_description():
    html = _html()
    # الخط الحرج الذي يعرض "سطر الدور" لكل وكيل من استجابة الخادم مباشرة.
    assert "d:a.role" in html
