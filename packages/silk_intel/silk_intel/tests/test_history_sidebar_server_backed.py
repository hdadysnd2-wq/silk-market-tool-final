"""إصلاح البند ١ب/ج (بلاغ حي تكلفة): شريط «بحوثي السابقة» الخادمي.

تحليلات مكتملة مدفوعة الثمن لا تظهر لاحقاً في الواجهة فيُعاد دفع ثمنها —
كان الشريط localStorage محضاً (لكل متصفّح، لا خادم). الآن مصدره GET /analyses
الخادمي: صفّ لكل تحليل (سوق/حكم/تكلفة/تاريخ/حالة)، وزر «استئناف» لتشغيلة
عالقة/فاشلة موصول بـPOST /research {resume, async_run:true} (يكمل البعثات
الناقصة فقط — لا حرق اعتمادات مضاعف).

هذا الملف يختبر الشقّ الأمامي الحقيقي فقط (الشقّ الخادمي: silk_storage.py +
tests/test_analysis_history_storage.py). التنفيذ عبر Node — الدالة المستخرجة
من web/index.html حرفياً، لا سلسلة نصّية تخمينية.

Run: python3 -m pytest tests/test_history_sidebar_server_backed.py -q
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


def _node():
    node = shutil.which("node")
    if not node:
        import pytest
        pytest.skip("node غير متاح في هذه البيئة — أفضل جهد")
    return node


def _extract_block(html: str) -> str:
    m = re.search(
        r"S\.serverHist=null;S\.serverHistStatus=\"idle\";.*?"
        r"openStoredAnalysis\(id\)\}\);",
        html, re.S)
    assert m, "لم يُعثر على كتلة الشريط الخادمي — هل انتقل الإصلاح أو تغيّر اسمه؟"
    return m.group(0)


# ---------------------------------------------------------------------------
# طبقة ١ — الشارات ونصوص العربية المطلوبة حاضرة في المصدر (فحص نصّي أدنى)
# ---------------------------------------------------------------------------

def test_source_declares_resume_button_and_states():
    html = _html()
    assert "data-resume-id=" in html
    assert "↻ استئناف" in html
    assert "لا بحوث سابقة بعد" in html
    assert "أدخل مفتاح الخدمة لعرض بحوثك السابقة" in html


def test_source_calls_correct_resume_endpoint_shape():
    html = _html()
    assert 'post("/research",{resume:Number(id),async_run:true})' in html


# ---------------------------------------------------------------------------
# طبقة ٢ — تنفيذ حقيقي عبر Node
# ---------------------------------------------------------------------------

_HARNESS = r"""
"use strict";
var calls = {toast: [], render: 0, nav: [], getJSON: [], post: []};
global.localStorage = {_d:{}, getItem:function(k){return this._d[k]||null}, setItem:function(k,v){this._d[k]=v}};
var S = {product:"تمور", view:{header:{target_market:"هولندا"}}, hist:[], busy:false};
function esc(s){return String(s==null?"":s).replace(/[&<>"]/g,function(c){return{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]})}
function toast(m){calls.toast.push(m)}
function renderBoard(){calls.render++}
function nav(v){calls.nav.push(v)}
function sync(){}
function makeEl(){var listeners=[];return{innerHTML:"",
  addEventListener:function(type,fn){listeners.push(fn)},
  _dispatch:function(ev){listeners.forEach(function(fn){fn(ev)})}}}
var histListEl = makeEl();
var researchBtnEl = {textContent:"بحث عميق"};
function $(sel){if(sel==="#histList")return histListEl;if(sel==="#researchBtn")return researchBtnEl;return makeEl()}
var _getMock = null, _postMock = null;
function getJSON(path){calls.getJSON.push(path);
  return new Promise(function(resolve,reject){
    if(_getMock.ok)resolve(_getMock.res);else reject(new Error(_getMock.message))})}
function post(path,body){calls.post.push({path:path,body:body});
  return new Promise(function(resolve,reject){
    if(_postMock.ok)resolve(_postMock.res);else reject(new Error(_postMock.message))})}
function pollResearchStatus(id,lbl){calls.poll=[id,lbl]}
function fakeTarget(attrs){
  return {
    closest:function(sel){
      if(sel==="[data-resume-id]")return (attrs.resumeId!=null)?this:null;
      if(sel===".hist")return (attrs.histId!==undefined)?this:null;
      return null},
    getAttribute:function(n){
      if(n==="data-resume-id")return attrs.resumeId;
      if(n==="data-id")return attrs.histId===null?"":String(attrs.histId);
      return null}}}

__FUNCS__

function reset(){calls={toast:[],render:0,nav:[],getJSON:[],post:[]};S.busy=false}
console.log("READY")
"""


def _run_node(js_body: str) -> str:
    node = _node()
    block = _extract_block(_html())
    script = _HARNESS.replace("__FUNCS__", block) + "\n" + js_body
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as f:
        f.write(script)
        tmp_path = f.name
    try:
        r = subprocess.run([node, tmp_path], capture_output=True, timeout=15)
        assert r.returncode == 0, r.stderr.decode()
        return r.stdout.decode()
    finally:
        os.unlink(tmp_path)


def test_web_history_block_parses_standalone():
    out = _run_node("")
    assert "READY" in out


def test_hist_row_html_shows_market_verdict_cost_date_no_resume_when_completed():
    out = _run_node(r"""
var row = {id:5, product:"تمور", market_name:"هولندا",
  verdict_label:"مراقبة السوق", cost_usd:1.6,
  created_at:"2026-07-10T10:00:00", status:"completed"};
console.log("ROW|" + histRowHtml(row));
""")
    line = [l for l in out.splitlines() if l.startswith("ROW|")][0]
    row_html = line[len("ROW|"):]
    assert 'data-id="5"' in row_html
    assert "هولندا" in row_html
    assert "مراقبة السوق" in row_html
    assert "s-warn" in row_html          # نغمة الحكم لـ"مراقبة السوق"
    assert "~$1.60" in row_html
    assert "2026-07-10" in row_html
    assert "data-resume-id" not in row_html   # تشغيلة مكتملة — لا زرّ استئناف


def test_hist_row_html_shows_resume_button_and_falls_back_to_product_when_failed():
    out = _run_node(r"""
var row = {id:7, product:"شاي", market_name:null, verdict_label:null,
  cost_usd:null, created_at:"2026-07-01", status:"failed"};
console.log("ROW|" + histRowHtml(row));
""")
    line = [l for l in out.splitlines() if l.startswith("ROW|")][0]
    row_html = line[len("ROW|"):]
    assert 'data-resume-id="7"' in row_html
    assert "فشلت" in row_html
    assert "شاي" in row_html   # لا market_name => يسقط إلى اسم المنتج، لا فراغ


def test_draw_hist_shows_loading_then_unauthorized_then_empty_then_rows():
    out = _run_node(r"""
S.serverHistStatus="loading"; drawHist();
console.log("A|"+histListEl.innerHTML);
S.serverHistStatus="unauthorized"; drawHist();
console.log("B|"+histListEl.innerHTML);
S.serverHistStatus="ok"; S.serverHist=[]; drawHist();
console.log("C|"+histListEl.innerHTML);
S.serverHist=[{id:1,product:"تمور",market_name:"هولندا",verdict_label:"مراقبة السوق",cost_usd:1.6,created_at:"2026-07-10",status:"completed"}];
drawHist();
console.log("D|"+histListEl.innerHTML);
""")
    lines = dict(l.split("|", 1) for l in out.splitlines() if "|" in l)
    assert "جارٍ التحميل" in lines["A"]
    assert "أدخل مفتاح الخدمة" in lines["B"]
    assert "لا بحوث سابقة بعد" in lines["C"]
    assert "هولندا" in lines["D"] and "data-id=\"1\"" in lines["D"]


def test_draw_hist_falls_back_to_local_storage_on_server_error_never_blank():
    out = _run_node(r"""
S.hist=[{label:"تمور · هولندا", id:9}];
S.serverHistStatus="error"; S.serverHist=null; drawHist();
console.log("E|"+histListEl.innerHTML);
""")
    line = [l for l in out.splitlines() if l.startswith("E|")][0]
    body = line[len("E|"):]
    assert "تعذّر تحميل السجلّ من الخادم" in body   # لا فشل صامت
    assert 'data-id="9"' in body                    # الاحتياط المحلي يظهر فعلاً


def test_click_on_resume_button_calls_resume_not_open_stored():
    out = _run_node(r"""
_postMock = {ok:true, res:{analysis_id:99, status:"running"}};
histListEl._dispatch({target: fakeTarget({resumeId:"7"}), stopPropagation:function(){}});
setTimeout(function(){
  console.log("POST|"+JSON.stringify(calls.post));
  console.log("GETJSON|"+JSON.stringify(calls.getJSON));
  console.log("POLL|"+JSON.stringify(calls.poll||null));
}, 20);
""")
    lines = dict(l.split("|", 1) for l in out.splitlines() if "|" in l)
    posted = json.loads(lines["POST"])
    assert len(posted) == 1
    assert posted[0]["path"] == "/research"
    assert posted[0]["body"] == {"resume": 7, "async_run": True}
    assert json.loads(lines["GETJSON"]) == []   # لا فتح تحليل مخزَّن — استئناف فقط
    assert json.loads(lines["POLL"]) == [99, "بحث عميق"]


def test_click_on_resume_button_when_run_already_completed_renders_directly():
    out = _run_node(r"""
_postMock = {ok:true, res:{analysis_id:12, view:{x:1}}};   // مكتملة أصلاً — بلا 202
_getMock = {ok:true, res:[]};   // loadServerHistory داخل pushHist
histListEl._dispatch({target: fakeTarget({resumeId:"12"}), stopPropagation:function(){}});
setTimeout(function(){
  console.log("RENDER|"+calls.render);
  console.log("NAV|"+JSON.stringify(calls.nav));
  console.log("POLL|"+JSON.stringify(calls.poll||null));
}, 20);
""")
    lines = dict(l.split("|", 1) for l in out.splitlines() if "|" in l)
    assert lines["RENDER"] == "1"
    assert json.loads(lines["NAV"]) == ["board"]
    assert json.loads(lines["POLL"]) is None   # لم تُستطلَع حالة — كانت مكتملة فعلاً


def test_click_on_normal_row_still_opens_stored_analysis_not_resume():
    out = _run_node(r"""
_getMock = {ok:true, res:{view:{x:1}, analysis_id:42}};
histListEl._dispatch({target: fakeTarget({histId:"42"}), stopPropagation:function(){}});
setTimeout(function(){
  console.log("GETJSON|"+JSON.stringify(calls.getJSON));
  console.log("POST|"+JSON.stringify(calls.post));
  console.log("RENDER|"+calls.render);
}, 20);
""")
    lines = dict(l.split("|", 1) for l in out.splitlines() if "|" in l)
    got = json.loads(lines["GETJSON"])
    assert got[0] == "/analyses/42"
    assert json.loads(lines["POST"]) == []   # فتح صفّ عادي لا يستدعي استئناف إطلاقاً
    assert lines["RENDER"] == "1"


def test_resume_click_while_busy_shows_toast_and_does_not_post():
    out = _run_node(r"""
S.busy = true;
histListEl._dispatch({target: fakeTarget({resumeId:"7"}), stopPropagation:function(){}});
setTimeout(function(){
  console.log("POST|"+JSON.stringify(calls.post));
  console.log("TOAST|"+JSON.stringify(calls.toast));
}, 20);
""")
    lines = dict(l.split("|", 1) for l in out.splitlines() if "|" in l)
    assert json.loads(lines["POST"]) == []
    assert len(json.loads(lines["TOAST"])) == 1
