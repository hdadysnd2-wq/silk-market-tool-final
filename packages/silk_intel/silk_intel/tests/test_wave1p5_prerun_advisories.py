"""Wave 1.5 — عائلة «الدراسة بالاتجاه الخاطئ» (A) + لوحة «جاهزية الدراسة» (D).

قفلٌ سلوكيّ هرمتيّ:
- عائلة A: أشقّاء استشارة ما قبل التشغيل (بلد المنشأ نفسه / عقوبات / فصل مقيَّد)
  — config-driven، صفر رمز دولة/HS مكتوب صلبًا في المنطق (عائلة hardcoded-
  product-rule)، والقاعدة تُعمَّم من البيانات (مرجع المالك + بلد منشأ env).
- عائلة D: `GET /research/readiness` يُعيد كلَّ تدهورٍ قبل الحجز كسطر ✓/⚠/✗ —
  المالك لا يعرف تدهورًا بعد الدفع.

هرمتي: الشبكة محجوبة، البيئة معزولة بـ`_env`، لا حجز/إنفاق (readiness قراءة فقط).
"""
import contextlib
import importlib
import inspect
import os
import re
import sys
import tempfile
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import silk_prerun as pr  # noqa: E402


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


def _block_net():
    return mock.patch("requests.sessions.Session.request",
                      side_effect=OSError("network disabled for offline test"))


# ═══ عائلة A — الأشقّاء config-driven ═══════════════════════════════════════

def test_self_origin_advisory_fires_for_origin_market_config_driven():
    """تصدير إلى بلد المنشأ نفسه => استشارة self_origin. بلدُ المنشأ من env
    (لا رمز دولة مكتوب صلبًا): تغييرُه ينقل الاستشارة لسوقٍ أخرى."""
    with _env(SILK_ORIGIN_ISO3=None):                 # الافتراضي SAU
        assert [a["kind"] for a in pr.sibling_advisories("080410", "SAU")] \
            == ["self_origin"]
        assert pr.sibling_advisories("080410", "ITA") == []
    with _env(SILK_ORIGIN_ISO3="ITA"):                # config-driven
        assert any(a["kind"] == "self_origin"
                   for a in pr.sibling_advisories("080410", "ITA"))
        assert all(a["kind"] != "self_origin"
                   for a in pr.sibling_advisories("080410", "SAU"))


def test_restricted_chapter_advisory_from_owner_reference():
    """فصلٌ مقيَّد (خنزير 0203 / روحية 2208) في سوقٍ خليجية => استشارة
    restricted_chapter من مرجع المالك؛ منتجٌ غير مقيَّد => لا استشارة."""
    hits = [a["kind"] for a in pr.sibling_advisories("020329", "SAU")]
    assert "restricted_chapter" in hits
    assert "restricted_chapter" not in [
        a["kind"] for a in pr.sibling_advisories("080410", "SAU")]  # تمور غير مقيَّد


def test_sanction_advisory_reads_marketwide_row(tmp_path):
    """صفٌّ بلا hs_prefix => قيدُ سوقٍ كامل (عقوبات) لأيّ رمز HS."""
    csv = tmp_path / "restricted.csv"
    csv.write_text(
        "market_iso3,hs_prefix,kind,reason_ar,source_url\n"
        "ZZZ,,sanction,سوق تحت عقوبات (عيّنة اختبار),https://example.invalid\n",
        encoding="utf-8")
    pr._load_restricted.cache_clear()
    try:
        with mock.patch.object(pr, "_RESTRICTED_CSV", str(csv)):
            kinds = [a["kind"] for a in pr.sibling_advisories("999999", "ZZZ")]
        assert "sanction" in kinds
    finally:
        pr._load_restricted.cache_clear()


def test_missing_reference_fails_open_silent():
    """مرجع القيود الغائب => لا استشارة قيود (فشل آمن مفتوح) — لا كسر."""
    pr._load_restricted.cache_clear()
    try:
        with mock.patch.object(pr, "_RESTRICTED_CSV", "/nonexistent/x.csv"):
            # بلد المنشأ ما زال يعمل (env)، لكن لا قيود من ملفٍ غائب.
            kinds = [a["kind"] for a in pr.sibling_advisories("020329", "SAU")]
        assert kinds == ["self_origin"]
    finally:
        pr._load_restricted.cache_clear()


def test_prerun_logic_has_no_hardcoded_market_or_hs_literal():
    """عائلة hardcoded-product-rule: منطقُ المطابقة يخلو من أيّ رمز HS مكتوب
    صلبًا أو قائمة أسواق — كلّه من المرجع (CSV) والبيئة (origin)."""
    blob = "\n".join(inspect.getsource(fn) for fn in (
        pr.sibling_advisories, pr._restricted_hits, pr._load_restricted))
    codes = re.findall(r"(?<!\d)\d{4,6}(?!\d)", blob)
    assert not codes, f"رمز HS مكتوب صلبًا في منطق الاستشارة: {codes}"
    # لا قائمة أسواق مكتوبة صلبًا: لا رمز ISO3 حرفيّ في منطق المطابقة.
    isos = re.findall(r'"[A-Z]{3}"', blob)
    assert not isos, f"رمز دولة مكتوب صلبًا في منطق المطابقة: {isos}"
    # المرجع config-driven (ملف بيانات).
    assert "restricted_markets.csv" in inspect.getsource(pr)


# ═══ /research gate — الأشقّاء خلف الصمّام + الموافقة الموحّدة ════════════════

def _client():
    import api
    importlib.reload(api)
    from fastapi.testclient import TestClient
    return TestClient(api.create_app())


def test_research_sibling_advisory_422_until_advisories_ack():
    """SILK_PRERUN_ADVISORIES=1 + سوق بلد المنشأ => 422 prerun_advisory قبل
    الحجز؛ ثم advisories_ack=true يعبر البوّابة (لا يتكرّر)."""
    pytest.importorskip("fastapi")
    with _env(SILK_PRERUN_ADVISORIES="1", SILK_ORIGIN_ISO3="SAU",
              SILK_API_KEY=None, ANTHROPIC_API_KEY=None), _block_net():
        c = _client()
        body = {"product": "تمور", "market": "SAU", "hs_code": "080410"}
        r1 = c.post("/research", json=body)
        r2 = c.post("/research", json=dict(body, advisories_ack=True))
    assert r1.status_code == 422 and r1.json()["detail"]["error"] == "prerun_advisory"
    assert any(a["kind"] == "self_origin"
               for a in r1.json()["detail"]["advisories"])
    assert not (r2.status_code == 422
                and r2.json()["detail"].get("error") == "prerun_advisory")


def test_research_sibling_advisory_flag_off_never_fires():
    """الصمّام مُطفأ (افتراضي) => لا استشارة أشقّاء (السلوك كاليوم)."""
    pytest.importorskip("fastapi")
    with _env(SILK_PRERUN_ADVISORIES=None, SILK_API_KEY=None,
              ANTHROPIC_API_KEY=None), _block_net():
        r = _client().post("/research",
                           json={"product": "تمور", "market": "SAU",
                                 "hs_code": "080410"})
    assert not (r.status_code == 422
                and r.json()["detail"].get("error") == "prerun_advisory")


# ═══ عائلة D — لوحة «جاهزية الدراسة» ════════════════════════════════════════

def test_readiness_panel_lists_blocking_and_advisory_before_run():
    """readiness يُعيد hs_resolved=ok + self_origin=advisory (بلد المنشأ)،
    can_run=true (لا حاجب)، needs_ack=true — كلُّ ذلك قبل أيّ حجز/إنفاق."""
    pytest.importorskip("fastapi")
    with _env(SILK_PRERUN_ADVISORIES="1", SILK_ORIGIN_ISO3="SAU",
              SILK_API_KEY=None, ANTHROPIC_API_KEY=None), _block_net():
        r = _client().get("/research/readiness",
                          params={"product": "تمور", "market": "SAU",
                                  "hs_code": "080410"})
    assert r.status_code == 200
    body = r.json()
    keys = {c["key"]: c for c in body["checks"]}
    assert keys["hs_resolved"]["status"] == "ok"
    assert keys["self_origin"]["status"] == "advisory"
    assert body["can_run"] is True and body["needs_ack"] is True


def test_readiness_panel_blocks_on_unresolved_hs():
    """منتجٌ لا يُحلّ + بلا hs_code => hs_resolved=blocked، can_run=false —
    التدهور معروفٌ قبل الدفع (لا مفاجأة «—» بعد الحجز)."""
    pytest.importorskip("fastapi")
    with _env(SILK_API_KEY=None, ANTHROPIC_API_KEY=None), _block_net():
        r = _client().get("/research/readiness",
                          params={"product": "qwxzptvbmzzz لا يوجد",
                                  "market": "ITA"})
    body = r.json()
    keys = {c["key"]: c for c in body["checks"]}
    assert keys["hs_resolved"]["status"] == "blocked"
    assert keys["hs_resolved"]["blocking"] is True
    assert body["can_run"] is False


def test_readiness_is_read_only_no_reservation():
    """readiness لا يحجز تفعيلةً ولا دولارًا — قراءة فقط."""
    pytest.importorskip("fastapi")
    import silk_usage
    with tempfile.TemporaryDirectory() as td:
        usage = os.path.join(td, "usage.db")
        with _env(SILK_USAGE_DB=usage, SILK_PAID_DAILY_CAP="5",
                  SILK_PAID_DAILY_USD_CAP="10", SILK_API_KEY=None,
                  ANTHROPIC_API_KEY=None), _block_net():
            _client().get("/research/readiness",
                         params={"product": "تمور", "market": "ITA",
                                 "hs_code": "080410"})
            assert silk_usage.paid_calls_today(usage) == 0
            assert silk_usage.usd_spent_today(usage) == 0.0
