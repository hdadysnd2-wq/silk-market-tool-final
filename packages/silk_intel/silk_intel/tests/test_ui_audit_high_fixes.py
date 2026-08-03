"""اختبارات إصلاحات تدقيق الواجهة (BLOCKER+HIGH) — docs/UI_AUDIT_2026-07-15.md.

كل إصلاح مقفول بتنفيذ Node حقيقي للكتلة المستخرَجة من web/index.html (لا مجرد
وجود نصّ) + تأكيد ساكن على المصدر المشحون. المبدأ (نفس test_sidebar_reopen_
analysis.py، ونفس انضباط silk-operations): كل فعل واجهة إمّا ينجح أو يُظهر أثراً
مرئياً — أبداً لا فعل صامت ولا حالة عالقة.

HIGH#1 — زر الإرسال في الدردشة يبقى فعّالاً بصرياً أثناء الانشغال فيعود بصمت.
HIGH#2 — زر «التعميق/الدراسة العميقة» يوجّه لإعدادات لا تملك حقول مفاتيح (تضليل).
HIGH#3 — عطل استطلاع عابر لا يحفظ معرّف الاستئناف ⇒ نقرة تالية تُنفق مرتين.
HIGH#4 — اللوحة تُسقط إفصاح سنة البيانات الذي يُظهره Word/Markdown/الطرفية.

Run: python3 -m pytest tests/test_ui_audit_high_fixes.py -q
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_HTML = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "web", "index.html")


def _html() -> str:
    return open(_HTML, encoding="utf-8").read()


def _script() -> str:
    m = re.search(r"<script>(.*)</script>", _html(), re.S)
    assert m, "no inline <script> block found"
    return m.group(1)


def _fn(src: str, signature: str) -> str:
    """استخرج جسم دالة كاملاً عبر موازنة الأقواس المعقوفة — لا هشاشة حدود."""
    i = src.index(signature)
    b = src.index("{", i)
    depth = 0
    for j in range(b, len(src)):
        c = src[j]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return src[i:j + 1]
    raise AssertionError(f"unbalanced braces for {signature}")


def _run_node(script: str) -> dict:
    node = shutil.which("node")
    if not node:
        return {"_skipped": True}
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as f:
        f.write(script)
        p = f.name
    try:
        r = subprocess.run([node, p], capture_output=True, timeout=15)
        assert r.returncode == 0, r.stderr.decode()
        out = {}
        for ln in r.stdout.decode().strip().splitlines():
            if ln.startswith("{"):
                out = json.loads(ln)
        return out
    finally:
        os.unlink(p)


# ── DOM/toast shim مشترك ──────────────────────────────────────────────────
_SHIM = r"""
"use strict";
var CALLS = {toast: [], chatAdd: [], stopPoll: 0, sync: 0};
var ELS = {};
function el(id){ if(!ELS[id]) ELS[id]={id:id, disabled:false, value:"",
  textContent:"", innerHTML:"", _l:[], classList:{add:function(){},remove:function(){},toggle:function(){}},
  addEventListener:function(t,fn){this._l.push(fn)}, querySelector:function(){return el(id+' q')},
  closest:function(){return this}}; return ELS[id]; }
function $(sel){ return el(sel); }
function toast(m){ CALLS.toast.push(m); }
function esc(s){ return String(s==null?"":s); }
function t(k){ return ""; }
"""


# ── HIGH#4 — dataYearNote (دالة نقية، أوضح دليل سلوكي) ────────────────────

def test_high4_data_year_note_discloses_fallback_and_is_silent_only_when_absent():
    fn = _fn(_script(), "function dataYearNote(")
    harness = _SHIM + fn + r"""
var out = {
  // تراجُع السنة: يجب أن يُفصح صراحةً (كما Word/Markdown/الطرفية)
  fell_back: dataYearNote({year:2025, data_year:2024, year_fell_back:true}),
  // سنة مطابقة: إفصاح بسيط بلا جملة التراجُع
  same: dataYearNote({year:2024, data_year:2024, year_fell_back:false}),
  // لا سنة بيانات: فراغ (لا اختلاق)
  none: dataYearNote({year:2025, data_year:null}),
};
console.log(JSON.stringify(out));
"""
    r = _run_node(harness)
    if r.get("_skipped"):
        return
    assert "2024" in r["fell_back"] and "2025" in r["fell_back"]
    assert "لم تُنشر بعد" in r["fell_back"], "fallback must be disclosed, not hidden"
    assert "2024" in r["same"] and "لم تُنشر بعد" not in r["same"]
    assert r["none"] == "", "no data_year => empty, never a fabricated year"


def test_high4_wired_into_renderboard_before_kpis():
    html = _html()
    assert "function dataYearNote(" in html
    assert "html+=dataYearNote(v);" in html  # فعلاً مُستهلَك، لا محسوب معلّق


# ── HIGH#1 — send() يُعطي أثراً مرئياً أثناء الانشغال، وsync يعطّل الزر ──────

def test_high1_send_button_disabled_while_busy_in_sync():
    fn = _fn(_script(), "function sync()")
    harness = _SHIM + r"""
var S = {product:"تمر", market:null, span:5, busy:false};
function years(){ return [2020,2024]; }
""" + fn + r"""
S.busy = true; sync();
var busyDisabled = ELS["#sendBtn"] ? ELS["#sendBtn"].disabled : null;
S.busy = false; sync();
var idleDisabled = ELS["#sendBtn"] ? ELS["#sendBtn"].disabled : null;
console.log(JSON.stringify({busyDisabled: busyDisabled, idleDisabled: idleDisabled}));
"""
    r = _run_node(harness)
    if r.get("_skipped"):
        return
    assert r["busyDisabled"] is True, "#sendBtn must be disabled while S.busy"
    assert r["idleDisabled"] is False, "#sendBtn must be enabled when idle"


def test_high1_send_gives_visible_feedback_when_busy_not_silent():
    fn = _fn(_script(), "function send()")
    harness = _SHIM + r"""
var S = {busy:true};
function chatAdd(h,me){ CALLS.chatAdd.push(String(h)); return el('#bubble'); }
function parseChat(m){ return new Promise(function(){}); }  // لا يُحسَم
ELS["#chatBox"] = el("#chatBox"); ELS["#chatBox"].value = "ليش حصة السعودية منخفضة؟";
""" + fn + r"""
send();  // أثناء الانشغال
var busyState = {toast: CALLS.toast.length, chatAdd: CALLS.chatAdd.length,
                 boxKept: ELS["#chatBox"].value};
// الآن غير منشغل: يجب أن يتقدّم فعلاً
CALLS.toast = []; CALLS.chatAdd = []; S.busy = false;
send();
var okState = {chatAdd: CALLS.chatAdd.length, boxCleared: ELS["#chatBox"].value===""};
console.log(JSON.stringify({busy: busyState, ok: okState}));
"""
    r = _run_node(harness)
    if r.get("_skipped"):
        return
    # أثناء الانشغال: أثر مرئي (toast) دومًا، لا رسالة تُضاف، والنص محفوظ (لا يُمسح)
    assert r["busy"]["toast"] == 1, "busy send must toast — never a silent return"
    assert r["busy"]["chatAdd"] == 0, "busy send must not post the message"
    assert r["busy"]["boxKept"] != "", "busy send must keep the typed text"
    # غير منشغل: يتقدّم — يضيف الرسالة ويمسح الصندوق
    assert r["ok"]["chatAdd"] >= 1 and r["ok"]["boxCleared"] is True


# ── HIGH#3 — عطل الاستطلاع يحفظ معرّف الاستئناف (منع الإنفاق المضاعف) ──────

def test_high3_poll_failure_sets_resume_id_so_next_click_resumes():
    fn = _fn(_script(), "function pollResearchStatus(")
    harness = _SHIM + r"""
var S = {busy:true, lastFailedResearchId:null, researchPollTimer:null};
function stopResearchPoll(){ CALLS.stopPoll++; }
function sync(){ CALLS.sync++; }
function researchProgressText(){ return "…"; }
function getJSON(path){ return Promise.reject(new Error("HTTP 502 — bad gateway")); }
""" + fn + r"""
pollResearchStatus(4242, "بحث عميق");
setTimeout(function(){
  console.log(JSON.stringify({
    lastFailed: S.lastFailedResearchId,
    busy: S.busy,
    toastMentionsId: CALLS.toast.some(function(m){return m.indexOf("4242")>=0}),
    toasted: CALLS.toast.length
  }));
}, 30);
"""
    r = _run_node(harness)
    if r.get("_skipped"):
        return
    assert r["lastFailed"] == 4242, "transient poll failure must store the resume id"
    assert r["busy"] is False, "busy must be cleared so the button is usable"
    assert r["toasted"] >= 1 and r["toastMentionsId"], "must surface a visible resume hint with the id"


# ── HIGH#2 — نص «التعميق» صادق لا يوجّه لإعدادات بلا حقول مفاتيح ───────────

def test_high2_deepen_toast_is_honest_not_misdirecting_to_settings():
    html = _html()
    # التوجيه المضلِّل القديم أُزيل من كلا موقعي #deepBtn
    assert "فعّلها من الإعدادات" not in html, \
        "misdirecting 'enable from settings' text must be gone (settings has no key fields)"
    # النص الصادق: المفاتيح تُضبط على الخادم، غير متاح في هذا التشغيل
    assert html.count("تُضبط على الخادم (Railway) — غير متاح في هذا التشغيل") == 2, \
        "both #deepBtn handlers must carry the honest server-gated message"


# ── HIGH#5 — فتح تحليل كلاسيكي من الشريط لا يُظهر لوحة فارغة ───────────────
# (خادمي: البلوب الكلاسيكي يُخزَّن بلا view؛ GET /analyses/{id} كان يعيده كما هو،
#  فنقر «التحليلات الأخيرة» على تحليل /analyze يفتح «شغّل تحليلاً أولاً» الفارغة.)

import tempfile as _tf
from unittest import mock as _mock


def _client_with_db(db_path):
    from fastapi.testclient import TestClient
    import importlib
    import api
    importlib.reload(api)
    return TestClient(api.app)


def test_high5_get_analysis_rebuilds_view_for_classic_blob_persisted_without_it():
    import silk_storage
    db = os.path.join(_tf.mkdtemp(), "silk.db")
    # بلوب كلاسيكي كما يخزّنه المحرّك: بلا مفتاح view إطلاقاً (المحرّك يحفظ قبل
    # إرفاق العرض) — هذا هو الشكل الحقيقي المُسبِّب للّوحة الفارغة عند إعادة الفتح.
    classic = {"product": "تمر", "hs_code": "080410", "year": 2024,
               "markets": [{"iso3": "NLD", "name_en": "Netherlands",
                            "total_score": 0.61, "components_detail": []}]}
    with _mock.patch("silk_storage._db_path", return_value=db):
        aid = silk_storage.save_analysis(classic, db)
        assert "view" not in silk_storage.get_analysis(aid), \
            "precondition: classic blob is persisted WITHOUT a view"
        with _mock.patch.dict(os.environ, {"SILK_API_KEY": "secret"}):
            client = _client_with_db(db)
            r = client.get(f"/analyses/{aid}", headers={"X-API-Key": "secret"})
    assert r.status_code == 200
    body = r.json()
    # الإصلاح: العرض يُعاد بناؤه خادمياً فلا تفتح اللوحة فارغة.
    assert body.get("view"), "GET /analyses/{id} must rebuild view for a classic blob"
    assert body["view"].get("product") == "تمر" or body["view"].get("header"), \
        "rebuilt view must reflect the analysis, not an empty shell"
    assert body.get("analysis_id") == aid


def test_high5_does_not_disturb_a_blob_that_already_has_a_view():
    import silk_storage
    db = os.path.join(_tf.mkdtemp(), "silk.db")
    # مسار /research يحفظ *مع* view (وحكم بوابة الجودة داخله) — يجب ألّا يُعاد بناؤه.
    sentinel = {"product": "تمر", "markets": [],
                "view": {"_sentinel": True, "deep_research": {"quality_gate": "keep-me"}}}
    with _mock.patch("silk_storage._db_path", return_value=db):
        aid = silk_storage.save_analysis(sentinel, db)
        with _mock.patch.dict(os.environ, {"SILK_API_KEY": "secret"}):
            client = _client_with_db(db)
            r = client.get(f"/analyses/{aid}", headers={"X-API-Key": "secret"})
    assert r.status_code == 200
    v = r.json().get("view") or {}
    assert v.get("_sentinel") is True, "an existing (research) view must be returned untouched"
    assert v.get("deep_research", {}).get("quality_gate") == "keep-me"


# ── سلامة عامة ────────────────────────────────────────────────────────────

def test_web_script_still_parses_after_all_fixes():
    node = shutil.which("node")
    if not node:
        return
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as f:
        f.write(_script())
        p = f.name
    try:
        r = subprocess.run([node, "--check", p], capture_output=True)
        assert r.returncode == 0, r.stderr.decode()
    finally:
        os.unlink(p)
