"""اختبارات: نقر «التحليلات الأخيرة» يفتح التحليل المخزَّن فعلياً.

بلاغ حي: عناصر الشريط الجانبي تُعرَض (هولندا/إسبانيا/إثيوبيا…) لكن النقر
عليها لا يفعل شيئاً — سقوط صامت، وGET /analyses المباشر يعيد 401. التشخيص من
الشيفرة (لا تخمين، راجع silk-operations §4 «أكِّد السبب من الشيفرة»):
drawHist()/pushHist() لم تُخزِّنا analysis_id قط، ولا معالج نقر أُرفِق
بـ#histList إطلاقاً رغم `cursor:pointer` في تنسيق `.hist` — الأخير دليل أن
العنصر صُمِّم ليكون قابلاً للنقر لكن لم يُربَط قط. هذه **فجوة كامنة سابقة
للتشديد الأمني**، لا انحدار سبَّبه — حارس `_require_key` على GET /analyses*
(C-1) صحيح ومقصود (يمنع تعداد مجهول لبطاقات تكلفة العملاء)؛ الثغرة بحتة في
الواجهة، ونفس نمط بلاغ ٢ («٤٠١ المبتلَع»، `test_wave7_agent_panel_fallback.py`).

الإصلاح: كل عنصر history يخزّن analysis_id (`data-id`)، ومعالج نقر مفوَّض على
#histList يفتح التحليل أو يُظهر رسالة عربية مرئية دوماً — أبداً لا فعل صامت.

Run: python3 -m pytest tests/test_sidebar_reopen_analysis.py -q
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


def _client():
    from fastapi.testclient import TestClient
    import api
    return TestClient(api.app)


# ---------------------------------------------------------------------------
# الطبقة ١ — تأكيد أن الحارس الخادمي صحيح ومقصود (لا عطل يحتاج تخفيفاً)
# ---------------------------------------------------------------------------

def test_backend_analyses_list_and_single_require_key_when_configured():
    from unittest.mock import patch
    with patch.dict(os.environ, {"SILK_API_KEY": "secret"}):
        c = _client()
        r1 = c.get("/analyses")
        r2 = c.get("/analyses/1")
    assert r1.status_code == 401
    assert r2.status_code == 401


# ---------------------------------------------------------------------------
# الطبقة ٢ — علامات الإصلاح في المصدر الفعلي المنشور (نمط الموجة ٧)
# ---------------------------------------------------------------------------

def test_hist_items_now_carry_a_stored_analysis_id():
    html = _html()
    assert 'data-id="' in html
    assert "id:id||null" in html


def test_histlist_has_a_real_click_listener_not_just_hover_css():
    html = _html()
    # كانت المشكلة بالضبط: تنسيق يوحي بقابلية النقر بلا معالج فعلي مطلقاً.
    assert ".hist{" in html and "cursor:pointer" in html
    assert '$("#histList").addEventListener("click"' in html


def test_click_shows_required_arabic_message_on_401_never_silent():
    html = _html()
    assert "يتطلب مفتاح الخدمة — أدخله من القائمة" in html
    assert "HTTP 401" in html


def test_legacy_entry_without_id_shows_visible_message_not_silent_noop():
    html = _html()
    assert "قديم بلا معرّف" in html


def test_web_script_block_still_parses_after_the_fix():
    node = shutil.which("node")
    if not node:
        return  # بيئة بلا node — أفضل جهد (نفس تساهل test_wave6/10)
    m = re.search(r"<script>(.*)</script>", _html(), re.S)
    assert m, "no inline <script> block found"
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as f:
        f.write(m.group(1))
        tmp_path = f.name
    try:
        r = subprocess.run([node, "--check", tmp_path], capture_output=True)
        assert r.returncode == 0, r.stderr.decode()
    finally:
        os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# الطبقة ٣ — تنفيذ حقيقي عبر Node: إثبات سلوكي لا مجرد وجود نصّ (أفضل جهد).
# "استنسخ ضد السلوك المنشور فعلاً لا TestClient فقط" — الشقّ الخادمي مُثبَت
# أعلاه (الطبقة ١)؛ هذا يُثبت الشقّ الأمامي الحقيقي: الدالة المستخرجة من
# web/index.html حرفياً، مُنفَّذة في محرّك JS حقيقي (Node)، لا سلسلة نصّية.
# ---------------------------------------------------------------------------

_HARNESS = r"""
"use strict";
var calls = {toast: [], render: 0, nav: [], getJSON: []};
global.localStorage = {_d:{}, getItem:function(k){return this._d[k]||null}, setItem:function(k,v){this._d[k]=v}};
var S = {product:"تمور", view:{header:{target_market:"هولندا"}}, hist:[]};
function esc(s){return String(s==null?"":s)}
function toast(m){calls.toast.push(m)}
function renderBoard(){calls.render++}
function nav(v){calls.nav.push(v)}
function sync(){}
function makeEl(){var listeners=[];return{innerHTML:"",
  addEventListener:function(type,fn){listeners.push(fn)},
  _dispatch:function(ev){listeners.forEach(function(fn){fn(ev)})}}}
var histListEl = makeEl();
function $(sel){if(sel==="#histList")return histListEl;return makeEl()}
var _mock = null;
function getJSON(path){calls.getJSON.push(path);
  return new Promise(function(resolve,reject){
    if(_mock.ok)resolve(_mock.res);else reject(new Error(_mock.message))})}
function fakeTarget(id){return{
  closest:function(sel){return sel===".hist"?this:null},
  getAttribute:function(n){return n==="data-id"?(id===null?"":String(id)):null}}}

__FUNCS__

function reset(){calls={toast:[],render:0,nav:[],getJSON:[]}}
function run(name, mock, clickId){
  reset(); _mock = mock;
  histListEl._dispatch({target: fakeTarget(clickId)});
  return new Promise(function(res){setTimeout(res, 20)}).then(function(){
    console.log(name + "|" + JSON.stringify(calls))})}

run("success", {ok:true, res:{view:{x:1}, analysis_id:42}}, 42)
  .then(function(){return run("unauthorized", {ok:false, message:"HTTP 401 — missing or invalid API key (send X-API-Key header)"}, 42)})
  .then(function(){return run("legacy_no_id", {ok:true, res:{}}, null)})
  .then(function(){return run("other_error", {ok:false, message:"HTTP 404 — analysis 999 not found"}, 999)})
  .catch(function(e){console.error("HARNESS ERROR: "+e.stack);process.exit(1)})
"""


def _extract_click_block(html: str) -> str:
    # ITEM ١ (شريط «بحوثي السابقة» الخادمي) وسّع هذه الكتلة: pushHist الآن
    # يستدعي loadServerHistory/histRowHtml/VERDICT_TONE المعرَّفة قبله — لزم
    # تحريك حدّ الاستخراج للخلف كي يبقى كل رمز مُستخدَم معرَّفاً في القِرن
    # المعزول (Node) بلا ReferenceError.
    m = re.search(
        r"S\.serverHist=null;S\.serverHistStatus=\"idle\";.*?"
        r"openStoredAnalysis\(id\)\}\);",
        html, re.S)
    assert m, "could not locate the history-sidebar..click block — did the fix move/rename?"
    return m.group(0)


def test_real_execution_proves_every_click_path_is_visible_never_silent():
    node = shutil.which("node")
    if not node:
        return  # بيئة بلا node — أفضل جهد، الطبقتان ١-٢ تكفيان كحدّ أدنى صارم
    block = _extract_click_block(_html())
    script = _HARNESS.replace("__FUNCS__", block)
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as f:
        f.write(script)
        tmp_path = f.name
    try:
        r = subprocess.run([node, tmp_path], capture_output=True, timeout=15)
        assert r.returncode == 0, r.stderr.decode()
        results = {}
        for line in r.stdout.decode().strip().splitlines():
            if "|" not in line:
                continue
            name, payload = line.split("|", 1)
            results[name] = json.loads(payload)

        # النجاح: يفتح فعلاً — render+nav استُدعيا، لا سقوط صامت.
        succ = results["success"]
        assert succ["render"] == 1
        assert succ["nav"] == ["board"]
        # ITEM ١: فتح تحليل مخزَّن يُحدِّث الشريط من الخادم أيضاً (pushHist
        # الآن يستدعي loadServerHistory) — نداء خلفي ثانٍ إلى /analyses
        # بجانب /analyses/42 الأصلي؛ كلاهما GET محض (لا نداء كلود).
        assert succ["getJSON"] == ["/analyses/42", "/analyses"]

        # 401: الرسالة العربية المطلوبة بالضبط — لا سقوط صامت، لا رسالة مضلِّلة.
        unauth = results["unauthorized"]
        assert unauth["toast"] == ["يتطلب مفتاح الخدمة — أدخله من القائمة"]
        assert unauth["render"] == 0 and unauth["nav"] == []

        # عنصر قديم بلا معرّف: رسالة مرئية مختلفة، ولا محاولة fetch إطلاقاً.
        legacy = results["legacy_no_id"]
        assert legacy["getJSON"] == []
        assert len(legacy["toast"]) == 1 and "قديم" in legacy["toast"][0]

        # خطأ آخر (404 مثلاً): ليس "يتطلب مفتاح" المضلِّلة، لكن ليس صمتاً أيضاً.
        other = results["other_error"]
        assert len(other["toast"]) == 1
        assert "يتطلب مفتاح الخدمة" not in other["toast"][0]

        # القاعدة العامة عبر كل السيناريوهات: كل نقر ينتج أثراً مرئياً واحداً
        # على الأقل (toast أو نقل للوحة) — أبداً لا الاثنان صفر معاً.
        for name, r_ in results.items():
            visible = len(r_["toast"]) > 0 or r_["render"] > 0
            assert visible, f"scenario {name} produced NO visible effect — silent no-op"
    finally:
        os.unlink(tmp_path)
