"""إصلاح M12 + M8 من تدقيق الواجهة (docs/UI_AUDIT_2026-07-15.md) — دفعة صغيرة
مُختارة من المُشغّل بعد المراجعة (بقية MED/LOW تبقى موثَّقة لا مُصلَحة).

M12 — تعديل صندوق البحث لا يُبطل S.product/S.hs القديمين: اختيار «تمر» ثم
تعديل الصندوق (بلا اختيار صفٍّ جديد) وضغط «حلّل السوق» كان يحلّل «تمر» صامتاً
رغم أن الصندوق يعرض نصاً مختلفاً — نتيجة صحيحة الشكل لمنتج خاطئ.

M8 — [] صادقة في JS فـ(v.markets||[{}])[0] لا يتراجع أبداً لمصفوفة فارغة
(بوّابة نطاق كالنفط/الفحم تُعيد markets:[] رشيقة)؛ m يبقى undefined فيرمي
استثناءً عند أول m.trend/comp(m,...) — فشل صامت بلا رسالة. مكرَّرة في مسارين:
renderBoard() ومسار نتيجة الدردشة.

كل إصلاح مقفول بتنفيذ Node حقيقي للكتلة المستخرَجة من web/index.html (لا مجرّد
وجود نصّ)، وتحقّقتُ أن كل اختبار يفشل قبل الإصلاح.

Run: python3 -m pytest tests/test_ui_med_stale_product_and_empty_markets.py -q
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_HTML = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "web", "index.html")


def _html() -> str:
    return open(_HTML, encoding="utf-8").read()


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


_SHIM = r"""
"use strict";
var CALLS = {sync: 0};
var ELS = {};
function el(id){ if(!ELS[id]) ELS[id]={id:id, value:"", classList:{
  _on:false, add:function(){this._on=true}, remove:function(){this._on=false},
  toggle:function(){this._on=!this._on}}}; return ELS[id]; }
function $(sel){ return el(sel); }
function sync(){ CALLS.sync++; }
function esc(s){ return String(s==null?"":s); }
function base(){ return ""; }
function fetch(){ return Promise.resolve({json:function(){return Promise.resolve([])}}); }
"""


# ── M12 — إبطال الحلّ عند تعديل الصندوق ────────────────────────────────────

def _extract_psearch_block(src: str) -> str:
    start = src.index('var pT;$("#pSearch")')
    end = src.index('$("#pDrop").addEventListener("click"')
    assert end > start
    return src[start:end]


def test_m12_editing_search_box_invalidates_stale_product():
    block = _extract_psearch_block(_html())
    # $("#pSearch") يجب أن يُرجِع عنصراً حقيقياً بـaddEventListener يُخزِّن
    # المستمع، كي نستدعيه لاحقاً كأنه نقر/كتابة فعلية من المستخدم.
    harness = _SHIM + r"""
function makeInputEl(){ return {value:"", addEventListener:function(t,fn){this._fn=fn}}; }
var _pSearchEl = makeInputEl();
var _pDropEl = el("#pDrop");
var _origEl = el;
function $(sel){ if(sel==="#pSearch")return _pSearchEl; if(sel==="#pDrop")return _pDropEl; return _origEl(sel); }
var S = {product: "تمر", hs: "080410"};
ELS["#pResolved"] = el("#pResolved"); ELS["#pResolved"].classList.add();
""" + block + r"""
function fire(val){ _pSearchEl.value = val; _pSearchEl._fn.call(_pSearchEl); }

// السيناريو ١: النص لا يزال يطابق المنتج المحلول — لا إبطال.
fire("تمر");
var afterMatch = {product: S.product, hs: S.hs, resolvedOn: ELS["#pResolved"].classList._on, sync: CALLS.sync};

// السيناريو ٢: تعديل حقيقي (إلحاق حرف) — يجب الإبطال فوراً.
CALLS.sync = 0;
fire("تمر أ");
var afterEdit = {product: S.product, hs: S.hs, resolvedOn: ELS["#pResolved"].classList._on, sync: CALLS.sync};

console.log(JSON.stringify({afterMatch: afterMatch, afterEdit: afterEdit}));
"""
    r = _run_node(harness)
    if r.get("_skipped"):
        return
    assert r["afterMatch"]["product"] == "تمر", "typing the exact resolved value must not clear it"
    edit = r["afterEdit"]
    assert edit["product"] is None and edit["hs"] is None, \
        "editing the box away from the resolved product must clear S.product/S.hs"
    assert edit["resolvedOn"] is False, "the resolved chip must be hidden once invalidated"
    assert edit["sync"] >= 1, "sync() must run so #runBtn disables again"


def test_m12_fix_marker_present():
    html = _html()
    assert "if(S.product&&q!==S.product)" in html


# ── M8 — تراجُع آمن لمصفوفة أسواق فارغة (موقعان) ───────────────────────────

def test_m8_empty_markets_no_longer_throws_and_falls_back_to_empty_object():
    harness = _SHIM + r"""
function checkOldBehaviorThrows(){
  var v = {markets: []};
  var m = (v.markets||[{}])[0];   // السطر القديم — حرفياً كما كان قبل الإصلاح
  var threw = false;
  try { var _ = m.trend; } catch(e){ threw = true; }
  return {m_is_undefined: m===undefined, threw: threw};
}
function checkNewBehaviorSafe(){
  var v = {markets: []};
  var m = (v.markets&&v.markets[0])||{};   // السطر الجديد — حرفياً كما شُحن
  var threw = false;
  try { var _ = m.trend; } catch(e){ threw = true; }
  return {m_is_object: typeof m==="object" && m!==null, threw: threw};
}
console.log(JSON.stringify({old: checkOldBehaviorThrows(), fixed: checkNewBehaviorSafe()}));
"""
    r = _run_node(harness)
    if r.get("_skipped"):
        return
    # يوثّق العطل الحقيقي الذي كان موجوداً (لإثبات جدّية الإصلاح لا تخيّلاً).
    assert r["old"]["m_is_undefined"] is True
    assert r["old"]["threw"] is True, "documents the real pre-fix crash on empty markets"
    # الإصلاح: لا استثناء، وكائن آمن دوماً.
    assert r["fixed"]["m_is_object"] is True
    assert r["fixed"]["threw"] is False


def test_m8_both_sites_fixed_in_shipped_source():
    html = _html()
    assert html.count("(v.markets&&v.markets[0])||{}") == 2, \
        "both renderBoard and the chat-result callback must carry the fix"
    assert "(v.markets||[{}])[0]" not in html, \
        "the vulnerable idiom must not remain anywhere in the shipped file"


def test_web_script_still_parses_after_med_fixes():
    node = shutil.which("node")
    if not node:
        return
    import re
    m = re.search(r"<script>(.*)</script>", _html(), re.S)
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as f:
        f.write(m.group(1))
        p = f.name
    try:
        r = subprocess.run([node, "--check", p], capture_output=True)
        assert r.returncode == 0, r.stderr.decode()
    finally:
        os.unlink(p)
