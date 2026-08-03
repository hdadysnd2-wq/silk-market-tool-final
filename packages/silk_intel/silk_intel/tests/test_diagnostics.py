"""اختبار التشخيص الحيّ — live source diagnostics (rebuild).

يقفل: بلا شبكة => الأساس unreachable وagents_can_work=False؛ ببيانات محقونة
=> ok؛ النقطة /diagnostics لا تُصدر 500. Never fabricates.
Run:  python3 -m pytest tests/test_diagnostics.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import silk_data_layer as dl
import silk_diagnostics as diag


class _Resp:
    def __init__(self, payload, status=200):
        self._p = payload
        self.status_code = status

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


def test_offline_core_unreachable(monkeypatch):
    monkeypatch.setattr(dl, "_http_get",
                        lambda url, params=None: (_ for _ in ()).throw(OSError("blocked")))
    for k in ("SEARCH_API_KEY", "GOOGLE_MAPS_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    out = diag.run_diagnostics(2022)
    assert out["agents_can_work"] is False
    ct = [s for s in out["sources"] if s["name"] == "UN Comtrade"][0]
    assert ct["state"] == "unreachable" and ct["hint"]
    # المصادر المفتاحية بلا مفتاح تُعلَن no_key لا فشلاً.
    assert any(s["state"] == "no_key" for s in out["sources"])


def test_injected_core_data_makes_agents_workable(monkeypatch):
    def ok(url, params=None):
        if "worldbank" in url or "indicator" in url:
            return _Resp([{"page": 1}, [{"date": "2022", "value": 78000}]])
        return _Resp({"data": [{"partnerCode": 0, "primaryValue": 4.1e8}]})
    monkeypatch.setattr(dl, "_http_get", ok)
    out = diag.run_diagnostics(2022)
    core = {s["name"]: s["state"] for s in out["sources"]}
    assert core["UN Comtrade"] == "ok" and core["World Bank"] == "ok"
    assert out["agents_can_work"] is True


def test_endpoint_never_500(monkeypatch):
    from fastapi.testclient import TestClient
    import api
    monkeypatch.setattr(dl, "_http_get",
                        lambda url, params=None: (_ for _ in ()).throw(OSError("x")))
    r = TestClient(api.app).get("/diagnostics")
    assert r.status_code == 200 and r.json()["agents_can_work"] is False
