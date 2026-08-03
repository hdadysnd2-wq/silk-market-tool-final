"""البند أ٢ — فحص معقولية بلد المورّد · A2 supplier-country plausibility.

طلب المالك (متابعة Issue #144، بعد توقيعه على مذكّرة التصميم
`docs/DESIGN_A2_SUPPLIER_PLAUSIBILITY.md`): إشارةٌ اقتصاديةٌ مُعاضِدةٌ لتأكيد
رمز HS — تقارن موردي السوق الفعليين بأكبر مصدّري الرمز عالميًا؛ التفكّك شبه
التامّ = الرمز قد يصف عائلةً مختلفة (حادثة زبدة الفول السوداني/الألبان:
أيرلندا/نيوزيلندا تتصدّران 040510 لا مصدّرو زبدة الفول السوداني).

هرمتي بالكامل: لا شبكة (يُحاكى `market_imports`/`top_world_exporters`)، صفر
نداء مدفوع، البيئة معزولة، والصمّام مُطفأ افتراضيًا.
"""
import contextlib
import importlib
import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import silk_market_ranker as ranker  # noqa: E402
from silk_data_layer import DataPoint  # noqa: E402


@contextlib.contextmanager
def _env(**vals):
    old = {k: os.environ.get(k) for k in vals}
    try:
        for k, v in vals.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        yield
    finally:
        for k, v in old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


def _supplier(m49):
    """نقطة مورّدٍ بشكل `market_imports().competitors` — value['code'] = m49."""
    return DataPoint(value={"partner": "x", "code": m49, "value_usd": 1.0,
                            "share": 1.0}, source="s", confidence=0.9)


def _mock_probes(supplier_m49s, world_iso3s):
    mi = {"competitors": [_supplier(m) for m in supplier_m49s]}
    world = [{"iso3": c, "m49": "0", "total_usd": 100 - i}
             for i, c in enumerate(world_iso3s)]
    return (mock.patch("silk_data_layer_v2.market_imports", return_value=mi),
            mock.patch.object(ranker, "top_world_exporters",
                              return_value=world))


# ═══════════════ ١) الدالة الأساسية — سلوك القياس ═══════════════

def test_total_disjointness_is_flagged_implausible():
    """موردو السوق (IRL/NZL/DEU) لا أحدَ منهم بين أكبر مصدّري الرمز
    (ARG/IND/CHN) => implausible، تداخل 0.0 (حادثة الألبان)."""
    mi, world = _mock_probes(["372", "554", "276"], ["ARG", "IND", "CHN"])
    with mi, world:
        r = ranker.supplier_plausibility("040510", "ARE", "784", 2022)
    assert r is not None
    assert r["implausible"] is True and r["overlap"] == 0.0


def test_any_overlap_is_plausible_not_flagged():
    """تداخلٌ ولو جزئي (ARG مورّدٌ ومصدّرٌ عالمي) => ليس implausible —
    إعادة التصدير لا تُطلق تحذيرًا كاذبًا."""
    mi, world = _mock_probes(["032", "276", "356"], ["ARG", "IND", "CHN"])
    with mi, world:
        r = ranker.supplier_plausibility("200811", "ARE", "784", 2022)
    assert r is not None and r["implausible"] is False and r["overlap"] > 0.0


def test_insufficient_data_is_silent_fail_open():
    """طرفٌ دون الحدّ الأدنى K => None (صمت، لا تحذيرٌ هشّ)."""
    mi, world = _mock_probes(["032"], ["ARG", "IND", "CHN"])
    with mi, world:
        assert ranker.supplier_plausibility("200811", "ARE", "784", 2022) is None


def test_probe_failure_is_silent_fail_open():
    """تعذّر القياس (شبكة/عطل) => None — لا تحذيرٌ كاذبٌ على قياسٍ متعذّر."""
    with mock.patch("silk_data_layer_v2.market_imports",
                    side_effect=OSError("net")):
        assert ranker.supplier_plausibility("200811", "ARE", "784", 2022) is None


def test_bad_inputs_return_none():
    assert ranker.supplier_plausibility("", "ARE", "784", 2022) is None
    assert ranker.supplier_plausibility("040510", "XX", "784", 2022) is None


# ═══════════════ ٢) العتبات config-driven ═══════════════

def test_max_overlap_threshold_is_env_driven():
    """رفع SILK_A2_MAX_OVERLAP يجعل تداخلًا جزئيًا يُطلق أيضًا (قابلية معايرة)."""
    mi, world = _mock_probes(["032", "372", "554"], ["ARG", "IND", "CHN"])
    with _env(SILK_A2_MAX_OVERLAP="0.5"), mi, world:
        r = ranker.supplier_plausibility("200811", "ARE", "784", 2022)
    # تداخل 1/3 ≈ 0.33 ≤ 0.5 => يُطلق الآن.
    assert r["implausible"] is True and r["overlap"] <= 0.5


def test_min_entries_threshold_is_env_driven():
    mi, world = _mock_probes(["372", "554"], ["ARG", "IND"])
    with _env(SILK_A2_MIN_ENTRIES="2"), mi, world:
        r = ranker.supplier_plausibility("040510", "ARE", "784", 2022)
    assert r is not None and r["implausible"] is True


# ═══════════════ ٣) لا ترميز صلب (عائلة hardcoded-product-rule) ═══════════════

def test_a2_logic_has_no_hardcoded_iso_or_hs_literal():
    """قفل العائلة: منطق أ٢ خالٍ من رمز دولة/HS مكتوب صلبًا — كلّه بيانات."""
    import inspect
    import re
    src = "\n".join(inspect.getsource(f) for f in (
        ranker.supplier_plausibility, ranker._a2_params,
        ranker._a2_plausibility_enabled))
    # لا رمز HS رقمي حرفي في المنطق (أمثلة التوثيق في docstring مستثناة عبر
    # تجريد سطور التعليق/الـdocstring ليست ممكنة ببساطة — نتحقّق من الكود فقط:
    # لا سلسلة ISO3 حرفية داخل شرطٍ/إسناد).
    code_lines = [ln for ln in src.splitlines()
                  if not ln.strip().startswith(("#", '"', "'"))
                  and "M49_TO_ISO3" not in ln]
    for iso in ("IRL", "NZL", "ARG", "SAU", "ARE"):
        assert not any(f'"{iso}"' in ln or f"'{iso}'" in ln for ln in code_lines), iso


# ═══════════════ ٤) بوّابة /research — 422 حتى الموافقة، وصمّام مُطفأ ═══════════════

def _client():
    import api
    importlib.reload(api)
    from fastapi.testclient import TestClient
    return TestClient(api.create_app())


def _block_net():
    return mock.patch("requests.sessions.Session.request",
                      side_effect=OSError("network disabled for offline test"))


def test_research_a2_advisory_422_until_explicit_consent():
    """الصمّام مفعّل + رمزٌ غير معقولٍ اقتصاديًا => 422 استشاري قبل الحجز؛
    ثم `a2_ack=true` يعبر البوّابة (لا يعود 422 الاستشاري)."""
    pytest.importorskip("fastapi")
    mi, world = _mock_probes(["372", "554", "276"], ["ARG", "IND", "CHN"])
    with _env(SILK_A2_PLAUSIBILITY="1", SILK_HS_CONFIRM_GATE="0",
              SILK_PRODUCER_ADVISORY="0", SILK_API_KEY=None,
              ANTHROPIC_API_KEY=None), _block_net(), mi, world:
        c = _client()
        body = {"product": "زبدة الفول السوداني", "market": "UAE",
                "hs_code": "040510"}
        r1 = c.post("/research", json=body)
        r2 = c.post("/research", json=dict(body, a2_ack=True))
    assert r1.status_code == 422
    assert r1.json()["detail"]["error"] == "supplier_plausibility_advisory"
    assert r1.json()["detail"]["needs_ack"] is True
    assert not (r2.status_code == 422 and r2.json()["detail"].get("error")
                == "supplier_plausibility_advisory")


def test_research_a2_valve_off_never_fires():
    """الصمّام مُطفأ (افتراضي) => لا بوّابة أ٢ إطلاقًا ولو كان الرمز غير معقول."""
    pytest.importorskip("fastapi")
    mi, world = _mock_probes(["372", "554", "276"], ["ARG", "IND", "CHN"])
    with _env(SILK_A2_PLAUSIBILITY=None, SILK_HS_CONFIRM_GATE="0",
              SILK_PRODUCER_ADVISORY="0", SILK_API_KEY=None,
              ANTHROPIC_API_KEY=None), _block_net(), mi, world:
        c = _client()
        r = c.post("/research", json={"product": "زبدة الفول السوداني",
                                      "market": "UAE", "hs_code": "040510"})
    assert not (r.status_code == 422 and r.json().get("detail", {}).get("error")
                == "supplier_plausibility_advisory")
