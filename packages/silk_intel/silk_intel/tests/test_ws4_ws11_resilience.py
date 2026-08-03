"""WS4 + WS11.1 — صمود الشبكة ونظافة الأخطاء + سلسلة صمود الاتجاهات.

WS4:
  • قاطع الدائرة (`silk_circuit.CircuitBreaker`): يفتح بعد N فشلٍ متتالٍ،
    يهدأ ثم يتحوّل نصف-مفتوح، والنجاح يغلقه.
  • `_timeout_for`: مهلةٌ لكل مصدر (WB أطول من كومتريد)، قابلة للضبط بيئياً.
  • `_http_get`: قاطعٌ مفتوح ⇒ فشلٌ سريع بمحاولةٍ واحدة (لا حلقة إعادة)؛
    نجاحٌ يغلقه؛ حدث فشلٍ بنيويٌّ لا يرفع ولا يلفّق استجابة.
WS11.1:
  • `trends_interest_resilient`: pytrends يفشل ⇒ آخر لقطةٍ مخزَّنة موسومةً
    stale بتاريخها؛ لا لقطة ⇒ فجوة معلنة (لا اختلاق).

Run:  python3 -m pytest tests/test_ws4_ws11_resilience.py -q
"""
import contextlib
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from conftest import block_network  # noqa: E402


# ============================ WS4: circuit breaker ============================

def test_breaker_opens_after_threshold_and_success_closes():
    from silk_circuit import CircuitBreaker
    cb = CircuitBreaker(threshold=3, cooldown_s=60)
    assert not cb.is_open("h")
    cb.record_failure("h"); cb.record_failure("h")
    assert not cb.is_open("h")          # 2 < 3
    cb.record_failure("h")
    assert cb.is_open("h")              # 3 == threshold → open
    cb.record_success("h")
    assert not cb.is_open("h") and cb.failures("h") == 0


def test_breaker_half_opens_after_cooldown(monkeypatch):
    import silk_circuit
    cb = silk_circuit.CircuitBreaker(threshold=2, cooldown_s=30)
    t = {"now": 1000.0}
    monkeypatch.setattr(silk_circuit.time, "monotonic", lambda: t["now"])
    cb.record_failure("h"); cb.record_failure("h")
    assert cb.is_open("h")             # opened at t=1000
    t["now"] = 1025.0
    assert cb.is_open("h")             # still within 30s cooldown
    t["now"] = 1031.0
    assert not cb.is_open("h")         # cooldown elapsed → half-open (allow probe)


def test_breaker_reset_clears_state():
    from silk_circuit import CircuitBreaker
    cb = CircuitBreaker(threshold=1)
    cb.record_failure("a"); cb.record_failure("b")
    assert cb.is_open("a") and cb.is_open("b")
    cb.reset("a")
    assert not cb.is_open("a") and cb.is_open("b")
    cb.reset()
    assert not cb.is_open("b")


# ============================ WS4: per-source timeout =========================

def test_timeout_is_per_source_world_bank_longer_than_comtrade():
    import silk_data_layer as dl
    wb = dl._timeout_for("api.worldbank.org")
    ct = dl._timeout_for("comtradeapi.un.org")
    other = dl._timeout_for("example.com")
    assert wb > ct, "World Bank must get the longer window"
    assert ct == 30.0 and other == 30.0


def test_timeout_is_env_tunable(monkeypatch):
    import silk_data_layer as dl
    monkeypatch.setenv("SILK_WB_TIMEOUT_S", "90")
    monkeypatch.setenv("SILK_COMTRADE_TIMEOUT_S", "12")
    assert dl._timeout_for("api.worldbank.org") == 90.0
    assert dl._timeout_for("comtradeapi.un.org") == 12.0


# ============================ WS4: _http_get integration =====================

class _Resp:
    def __init__(self, status):
        self.status_code = status
        self.headers = {}

    def json(self):
        return {}


def _install_get(monkeypatch, dl, status_sequence):
    """يركّب _session.get يعيد أكواداً متسلسلة ويعدّ النداءات؛ يعطّل
    الخنق/النوم كي لا يبطئ الاختبار."""
    calls = {"n": 0}

    def fake_get(url, params=None, headers=None, timeout=None):
        i = min(calls["n"], len(status_sequence) - 1)
        calls["n"] += 1
        return _Resp(status_sequence[i])

    monkeypatch.setattr(dl._session, "get", fake_get)
    monkeypatch.setattr(dl, "_throttle", lambda host: None)
    monkeypatch.setattr(dl._time, "sleep", lambda s: None)
    return calls


def test_http_get_open_breaker_fails_fast_single_attempt(monkeypatch):
    import silk_data_layer as dl
    import silk_circuit
    silk_circuit.http_breaker.reset()
    calls = _install_get(monkeypatch, dl, [503])   # always retryable failure
    # مع الإعادات الافتراضية (3) نداءٌ فاشلٌ = 4 محاولات ويسجّل فشلاً واحداً.
    dl._http_get("https://x.example/api")
    assert calls["n"] == 4
    # 5 فشلٍ متتالٍ يفتح القاطع (العتبة الافتراضية 5) — نداءٌ لاحقٌ يفشل سريعاً.
    for _ in range(4):
        dl._http_get("https://x.example/api")
    assert silk_circuit.http_breaker.is_open("x.example")
    calls["n"] = 0
    dl._http_get("https://x.example/api")
    assert calls["n"] == 1, "open breaker must fail fast with a single attempt"
    silk_circuit.http_breaker.reset()


def test_http_get_success_closes_breaker(monkeypatch):
    import silk_data_layer as dl
    import silk_circuit
    silk_circuit.http_breaker.reset()
    calls = _install_get(monkeypatch, dl, [503, 503, 200])
    dl._http_get("https://y.example/api")   # recovers on 3rd attempt → success
    assert silk_circuit.http_breaker.failures("y.example") == 0
    assert not silk_circuit.http_breaker.is_open("y.example")
    silk_circuit.http_breaker.reset()


def test_structured_failure_event_never_raises_outside_trace():
    import silk_data_layer as dl
    # خارج سياق تتبّع = no-op صامت، لا استثناء، لا سلسلة خطأٍ فارغة العناصر.
    dl._record_fetch_failure_event("h", "https://h/api", status=503, attempt=4)


def test_structured_failure_event_lands_in_trace(tmp_path):
    import silk_data_layer as dl
    import silk_trace
    with silk_trace.trace_context("ws4trace", dir_path=str(tmp_path)):
        dl._record_fetch_failure_event("api.worldbank.org",
                                       "https://api.worldbank.org/v2/x",
                                       status=503, error_repr="", attempt=4)
    events = silk_trace.read_trace("ws4trace", dir_path=str(tmp_path))
    hit = [e for e in events if e.get("event") == "source_fetch_failed"]
    assert hit and hit[0]["source_id"] == "api.worldbank.org"
    assert hit[0]["status"] == 503 and hit[0]["attempt"] == 4
    # لا عنصرٌ فارغٌ يشبه «(), , ()» — كل الحقول مسمّاة بقيم صريحة (WS4).
    assert hit[0]["endpoint"].startswith("https://")


# ============================ WS11.1: trends snapshot ========================

@contextlib.contextmanager
def _tmp_store():
    d = tempfile.mkdtemp()
    saved = os.environ.get("SILK_STORE_DB")
    os.environ["SILK_STORE_DB"] = os.path.join(d, "store.db")
    try:
        import silk_store
        silk_store.migrate()
        yield silk_store
    finally:
        if saved is None:
            os.environ.pop("SILK_STORE_DB", None)
        else:
            os.environ["SILK_STORE_DB"] = saved


def test_trends_resilient_serves_stored_snapshot_when_live_fails():
    import silk_trends_agent as ta
    with _tmp_store() as store:
        # لقطةٌ سابقة مخزَّنة بنفس مفتاح الاتجاهات المنفصل.
        store.upsert_indicator(ta._snapshot_geo("NL"),
                               ta._snapshot_indicator("peanut butter"),
                               2026, 63.0, "Google Trends", 0.7, "prior pull")
        with block_network():   # pytrends غائب/مقطوع ⇒ الحيّ يفشل
            dp = ta.trends_interest_resilient("peanut butter", "NL")
        assert dp.value == 63.0            # خُدمت اللقطة، لا فجوة
        assert dp.status == "stale"        # موسومة غير حيّة
        assert dp.confidence <= 0.5        # ثقة مخفوضة
        assert "من المخزن" in dp.note      # مصرَّحٌ أنها مخزَّنة لا حيّة


def test_trends_stale_snapshot_surfaces_date_and_conf_in_trace(tmp_path):
    # حارس المالك ٢: تاريخ اللقطة + الثقة المسقوفة يظهران في تتبّع التشغيلة.
    import silk_trends_agent as ta
    import silk_trace
    with _tmp_store() as store:
        store.upsert_indicator(ta._snapshot_geo("NL"),
                               ta._snapshot_indicator("peanut butter"),
                               2026, 63.0, "Google Trends", 0.7, "prior")
        with silk_trace.trace_context("ws11trace", dir_path=str(tmp_path)):
            with block_network():
                ta.trends_interest_resilient("peanut butter", "NL")
    ev = [e for e in silk_trace.read_trace("ws11trace", dir_path=str(tmp_path))
          if e.get("event") == "trends_snapshot_served"]
    assert ev and ev[0]["status"] == "stale"
    assert ev[0]["observed_at"] and ev[0]["confidence"] <= 0.5


def test_trends_resilient_declares_gap_when_no_snapshot():
    import silk_trends_agent as ta
    with _tmp_store():
        with block_network():
            dp = ta.trends_interest_resilient("obscure kw", "ZZ")
        assert dp.value is None and dp.confidence == 0.0   # فجوة معلنة، لا اختلاق


def test_trends_snapshot_keys_are_namespaced_and_stable():
    import silk_trends_agent as ta
    assert ta._snapshot_indicator("Peanut Butter") == "trends:peanut butter"
    assert ta._snapshot_geo(None) == "WW" and ta._snapshot_geo("nl") == "NL"
