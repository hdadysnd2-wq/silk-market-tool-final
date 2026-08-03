"""اختبارات القرص الدائم — persistent-volume wiring (Railway /data).

يثبت أن متغير `SILK_DATA_DIR` الواحد يوجّه المخازن الأربعة (قاعدة التحليلات،
مخزن الحقائق، عدّاد الاستهلاك، ذاكرة الطلبات) لمسار القرص، وأن «إعادة نشر»
(عملية جديدة تمامًا على نفس مسار القرص) تجد الحقيقة المخزّنة وتخدمها **بلا
أي نداء شبكة** — هذا هو عقد «لا ندفع مرتين». المبدأ التأسيسي محفوظ: القيم
تُقرأ كما خُزّنت بمصدرها، والغياب يبقى غيابًا.
Proves one env var routes all four stores to the volume, and a fresh process
on the same volume path serves the stored fact with zero network calls.
"""
import json
import os
import subprocess
import sys

import silk_cache
import silk_storage
import silk_store
import silk_usage

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── اشتقاق المسارات · path derivation ───────────────────────────────────────

def test_data_dir_derives_all_store_paths(monkeypatch, tmp_path):
    """SILK_DATA_DIR وحده يوجّه المخازن الأربعة — one var, four stores."""
    for var in ("SILK_DB", "SILK_STORE_DB", "SILK_USAGE_DB", "SILK_CACHE_DIR"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("SILK_DATA_DIR", str(tmp_path))
    assert silk_storage._db_path() == os.path.join(str(tmp_path), "silk.db")
    assert silk_store._db_path() == os.path.join(str(tmp_path), "silk_store.db")
    assert silk_usage._db_path() == os.path.join(str(tmp_path), "usage.db")
    assert silk_cache._cache_dir() == os.path.join(str(tmp_path), "cache")


def test_explicit_vars_win_over_data_dir(monkeypatch, tmp_path):
    """المتغير الصريح يفوز على SILK_DATA_DIR — explicit per-store override wins."""
    monkeypatch.setenv("SILK_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SILK_DB", "/elsewhere/a.db")
    monkeypatch.setenv("SILK_STORE_DB", "/elsewhere/b.db")
    monkeypatch.setenv("SILK_USAGE_DB", "/elsewhere/c.db")
    monkeypatch.setenv("SILK_CACHE_DIR", "/elsewhere/cache")
    assert silk_storage._db_path() == "/elsewhere/a.db"
    assert silk_store._db_path() == "/elsewhere/b.db"
    assert silk_usage._db_path() == "/elsewhere/c.db"
    assert silk_cache._cache_dir() == "/elsewhere/cache"


def test_defaults_unchanged_without_env(monkeypatch):
    """بلا متغيرات: الافتراضيات المحلية كما كانت — local defaults untouched."""
    for var in ("SILK_DATA_DIR", "SILK_DB", "SILK_STORE_DB",
                "SILK_USAGE_DB", "SILK_CACHE_DIR"):
        monkeypatch.delenv(var, raising=False)
    assert silk_storage._db_path() == os.path.join("data", "silk.db")
    assert silk_store._db_path() == os.path.join("data", "silk_store.db")
    assert silk_usage._db_path() == os.path.join("data", "usage.db")
    assert silk_cache._cache_dir() == os.path.join("data", "cache")


def test_cache_dir_env_honored_end_to_end(monkeypatch, tmp_path):
    """cached_get يكتب ويقرأ من SILK_CACHE_DIR — الملف ينجو لعملية أخرى."""
    monkeypatch.setenv("SILK_CACHE_DIR", str(tmp_path / "cache"))

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"real": True}]}

    calls = {"n": 0}

    def fetcher(url, params):
        calls["n"] += 1
        return _Resp()

    out1 = silk_cache.cached_get("https://x.example/api", {"q": 1},
                                 fetcher=fetcher)
    assert out1 == {"data": [{"real": True}]}
    assert calls["n"] == 1
    assert os.listdir(str(tmp_path / "cache"))  # كُتب على «القرص»
    # القراءة الثانية من القرص — صفر جلب حي. Second read: zero live fetches.
    out2 = silk_cache.cached_get("https://x.example/api", {"q": 1},
                                 fetcher=fetcher)
    assert out2 == out1
    assert calls["n"] == 1


# ── محاكاة إعادة النشر · redeploy simulation (fresh process, same volume) ────

_WRITER = """
import os, sys
sys.path.insert(0, {repo!r})
import silk_store
silk_store.migrate()
silk_store.upsert_trade_flows([
    {{"hs6": "090111", "reporter_iso3": "DEU", "partner_iso3": "WLD",
      "year": 2023, "flow": "M", "value_usd": 1234567.0}},
    {{"hs6": "090111", "reporter_iso3": "DEU", "partner_iso3": "BRA",
      "year": 2023, "flow": "M", "value_usd": 700000.0}},
])
print("written")
"""

_READER = """
import json, os, socket, sys
sys.path.insert(0, {repo!r})

from silk_data_layer_v2 import market_imports_cached

def _no_net(*a, **k):
    raise AssertionError("network attempted — store should have served this")

socket.socket = _no_net  # الاستيراد تم؛ الآن أي نداء شبكة فعلي = فشل صريح

mi = market_imports_cached("090111", "276", "DEU", 2023)
comp = [c.value for c in mi["competitors"]]
print(json.dumps({{"total_usd": mi["total_usd"], "competitors": comp,
                   "sources": [c.source for c in mi["competitors"]]}}))
"""


def _run(code: str, env: dict) -> str:
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True,
                          text=True, env=env, cwd=_REPO, timeout=120)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def test_redeploy_preserves_fact_store_and_serves_without_network(tmp_path):
    """اكتب حقيقة، «أعد النشر» (عملية جديدة، نفس القرص)، اقرأها بلا شبكة.

    Write a fact; simulate a redeploy (fresh process, same volume path);
    assert the value is served from the store with the network hard-blocked.
    """
    env = {k: v for k, v in os.environ.items()
           if k not in ("SILK_DB", "SILK_STORE_DB", "SILK_USAGE_DB",
                        "SILK_CACHE_DIR")}
    env["SILK_DATA_DIR"] = str(tmp_path)

    assert _run(_WRITER.format(repo=_REPO), env) == "written"
    # القرص «نجا» من إعادة النشر — the volume file survived the "redeploy".
    assert os.path.exists(tmp_path / "silk_store.db")

    out = json.loads(_run(_READER.format(repo=_REPO), env))
    assert out["total_usd"] == 1234567.0
    assert out["competitors"] and out["competitors"][0]["value_usd"] == 700000.0
    # الإسناد يعلن أن القيمة من المخزن — provenance declares the store origin.
    assert any("مخزن" in s for s in out["sources"])


# ── LESSONS.md البند ٥: استئناف البعثات ينجو من إعادة النشر ─────────────────

_CKPT_WRITER = """
import os, sys
sys.path.insert(0, {repo!r})
import silk_storage as ST
from silk_agents import AgentReport
from silk_data_layer import DataPoint
aid = ST.create_research_run("تمور", "NLD", "080410", {{"product": "تمور"}})
for key in ("trade_flow", "demographics_economy", "competitors"):
    rep = AgentReport("LLMAgent:" + key,
                      [DataPoint(1.0, "src", 0.9, "note")], False, "ok")
    ST.save_mission_checkpoint(aid, key, rep)
print(aid)
"""

_CKPT_READER = """
import json, os, sys
sys.path.insert(0, {repo!r})
import silk_storage as ST
# load_mission_checkpoints مسار قرص محض (sqlite) — لا يجلب شبكةً بنيوياً؛
# الغرض هنا إثبات أن البعثات المكتملة نجت من «إعادة النشر» على القرص الدائم.
reports = ST.load_mission_checkpoints({aid})
print(json.dumps(sorted(reports.keys())))
"""


def test_redeploy_preserves_research_checkpoints_and_resume_reads_them(tmp_path):
    """LESSONS.md البند ٥: اكتب نقاط تفتيش بعثات، «أعد النشر» (عملية جديدة على
    نفس القرص)، ثم اقرأها بلا شبكة — «الاستئناف بالقروش لا بالدولارات» يتطلّب
    أن تنجو البعثات المكتملة من إعادة النشر فعلاً على القرص، لا في الذاكرة."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("SILK_DB", "SILK_STORE_DB", "SILK_USAGE_DB",
                        "SILK_CACHE_DIR")}
    env["SILK_DATA_DIR"] = str(tmp_path)

    aid = _run(_CKPT_WRITER.format(repo=_REPO), env).strip()
    assert aid.isdigit()
    # ملف قاعدة التحليلات نجا على «القرص» — the analyses DB file survived.
    assert os.path.exists(tmp_path / "silk.db")

    keys = json.loads(_run(_CKPT_READER.format(repo=_REPO, aid=aid), env))
    assert keys == ["competitors", "demographics_economy", "trade_flow"]


# ── LESSONS.md البند ٤: مصيدة إقلاع التخزين الفاني (fail-fast) ──────────────

def _reload_api_under(env_overrides: dict):
    """أعِد تحميل api داخل بيئة معدَّلة — يعيد (module|None, raised_msg|None).
    يوجَّه التخزين لمسار مؤقّت افتراضاً كي لا يكتب في مجلد المستودع."""
    import contextlib
    import importlib
    keys = ("SILK_REQUIRE_PERSISTENT_DATA_DIR", "SILK_ALLOW_NONMOUNT_PERSIST",
            "SILK_DATA_DIR", "SILK_DB",
            "VOLZA_API_KEY", "ANTHROPIC_API_KEY", "EXPLEE_API_KEY",
            "LOCALPRICE_API_KEY")
    saved = {k: os.environ.get(k) for k in keys}
    try:
        for k in keys:
            os.environ.pop(k, None)
        for k, v in env_overrides.items():
            os.environ[k] = v
        try:
            # الاستيراد الأول (بلا نسخة مخبّأة) ينفّذ جسم الوحدة تحت العلَم
            # فيرفع بنفسه — لذا داخل try؛ وإن كانت مخبّأة نُعيد التحميل تحته.
            import api
            importlib.reload(api)
            return api, None
        except RuntimeError as e:
            return None, str(e)
    finally:
        for k, old in saved.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old
        import api
        import importlib as _il
        _il.reload(api)  # أعِد الوحدة لحالة سليمة للاختبارات التالية


def test_create_app_refuses_ephemeral_storage_when_require_flag_set():
    """المصيدة مضبوطة بلا توجيه تخزين دائم => رفض الإقلاع بصوت عالٍ (RuntimeError)."""
    import pytest
    pytest.importorskip("fastapi")
    mod, msg = _reload_api_under({"SILK_REQUIRE_PERSISTENT_DATA_DIR": "1"})
    assert mod is None and msg is not None
    assert "SILK_DATA_DIR" in msg and "SILK_REQUIRE_PERSISTENT_DATA_DIR" in msg


def test_create_app_boots_when_require_flag_set_and_data_dir_present(tmp_path):
    """المصيدة مضبوطة مع SILK_DATA_DIR موجَّه لوحدة **مركّبة فعلًا** => إقلاع
    سليم. نحاكي وحدة تخزين حقيقية بـ ismount=True (tmp_path ليس نقطة تركيب)."""
    import pytest
    from unittest.mock import patch
    pytest.importorskip("fastapi")
    with patch("os.path.ismount", return_value=True):
        mod, msg = _reload_api_under({"SILK_REQUIRE_PERSISTENT_DATA_DIR": "1",
                                      "SILK_DATA_DIR": str(tmp_path)})
    assert msg is None and mod is not None and mod.app is not None


def test_create_app_boots_when_require_flag_set_and_explicit_silk_db(tmp_path):
    """SILK_DB الصريح وحده يكفي المصيدة (نفس تتالي _db_path) — لا رفض حين
    مجلّده وحدة مركّبة."""
    import pytest
    from unittest.mock import patch
    pytest.importorskip("fastapi")
    with patch("os.path.ismount", return_value=True):
        mod, msg = _reload_api_under({
            "SILK_REQUIRE_PERSISTENT_DATA_DIR": "1",
            "SILK_DB": str(tmp_path / "silk.db")})
    assert msg is None and mod is not None


def test_create_app_refuses_when_data_dir_set_but_not_a_real_mount(tmp_path):
    """تقوية (بلاغ المالك): SILK_DATA_DIR مضبوط لكن **لا وحدة مركّبة** على
    مساره (ismount=False طوال الصعود => جذر الحاوية الفاني) => رفض إقلاع
    بصوت عالٍ. هذا بالضبط السيناريو الذي كان يمسح الدراسات المدفوعة بصمت."""
    import pytest
    from unittest.mock import patch
    pytest.importorskip("fastapi")
    with patch("os.path.ismount", return_value=False):
        mod, msg = _reload_api_under({"SILK_REQUIRE_PERSISTENT_DATA_DIR": "1",
                                      "SILK_DATA_DIR": str(tmp_path)})
    assert mod is None and msg is not None
    assert "وحدة تخزين مركّبة" in msg and str(tmp_path) in msg


def test_create_app_boots_nonmount_when_escape_hatch_set(tmp_path):
    """المخرج الصريح SILK_ALLOW_NONMOUNT_PERSIST=1 (مضيفٌ قرصه الجذري دائم)
    => يقلع رغم أن المسار ليس نقطة تركيب منفصلة. قرار مشغّل صريح لا صمت."""
    import pytest
    from unittest.mock import patch
    pytest.importorskip("fastapi")
    with patch("os.path.ismount", return_value=False):
        mod, msg = _reload_api_under({
            "SILK_REQUIRE_PERSISTENT_DATA_DIR": "1",
            "SILK_ALLOW_NONMOUNT_PERSIST": "1",
            "SILK_DATA_DIR": str(tmp_path)})
    assert msg is None and mod is not None


def test_create_app_boots_by_default_without_require_flag_even_with_paid_key():
    """غياب المصيدة = وضع تطوير مفتوح (نفس عقد المشروع): حتى مع مفتاح مدفوع
    وبلا SILK_DATA_DIR لا رفض إقلاع — التحذير الدائم على /health يكفي هنا."""
    import pytest
    pytest.importorskip("fastapi")
    mod, msg = _reload_api_under({"VOLZA_API_KEY": "paid-key-present"})
    assert msg is None and mod is not None


# ── وحدة: persistence_status (تمييز «مضبوط» عن «مركّب فعلًا») ────────────────

def test_persistence_status_unconfigured(monkeypatch):
    """بلا أي متغيّر تخزين => configured=False وكل الحقول محايدة."""
    for var in ("SILK_DATA_DIR", "SILK_DB"):
        monkeypatch.delenv(var, raising=False)
    st = silk_storage.persistence_status()
    assert st["configured"] is False
    assert st["is_mount"] is False and st["path"] is None


def test_persistence_status_configured_real_mount(monkeypatch, tmp_path):
    """SILK_DATA_DIR على وحدة مركّبة (ismount=True) + قابل للكتابة =>
    is_mount=True و writable=True والمسار هو نقطة التركيب."""
    from unittest.mock import patch
    monkeypatch.delenv("SILK_DB", raising=False)
    monkeypatch.setenv("SILK_DATA_DIR", str(tmp_path))
    with patch("os.path.ismount", return_value=True):
        st = silk_storage.persistence_status()
    assert st["configured"] and st["is_mount"] and st["writable"]
    assert st["path"] == str(tmp_path)


def test_persistence_status_configured_but_not_mounted(monkeypatch, tmp_path):
    """SILK_DATA_DIR مضبوط لكن بلا وحدة مركّبة (ismount=False) => is_mount=False
    رغم configured=True — هذا هو الفخّ الذي يمسح الدراسات بصمت."""
    from unittest.mock import patch
    monkeypatch.delenv("SILK_DB", raising=False)
    monkeypatch.setenv("SILK_DATA_DIR", str(tmp_path))
    with patch("os.path.ismount", return_value=False):
        st = silk_storage.persistence_status()
    assert st["configured"] is True and st["is_mount"] is False
    # قابل للكتابة يبقى صحيحًا (المجلّد المؤقّت يُكتب) — الفخّ ليس الكتابة بل
    # فناء القرص عند إعادة النشر؛ لذا is_mount هو الكاشف الوحيد.
    assert st["writable"] is True


def test_persistence_status_unwritable_path(monkeypatch, tmp_path):
    """مسار غير قابل للكتابة (فشل المجسّ) => writable=False بلا استثناء."""
    from unittest.mock import patch
    monkeypatch.delenv("SILK_DB", raising=False)
    monkeypatch.setenv("SILK_DATA_DIR", str(tmp_path))
    with patch("tempfile.mkstemp", side_effect=OSError("read-only fs")):
        st = silk_storage.persistence_status()
    assert st["configured"] is True and st["writable"] is False
