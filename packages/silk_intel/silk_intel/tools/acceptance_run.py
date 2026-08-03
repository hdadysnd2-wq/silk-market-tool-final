#!/usr/bin/env python3
"""تشغيلة قبول R1 الحيّة — سكربت واحد: POST /research ← استطلاع حتى الاكتمال
← سحب docx العميل + المختصر + Markdown + ثلاثة أسئلة دردشة،
وحفظ كل شيء في مجلّد للمراجعة، مع فحوص آلية (مصطلحات محظورة/تكلفة/تغطية).

الاستعمال (الصقْ مفتاحك وشغّل):

    SILK_API_BASE="https://<your-railway-app>"  SILK_API_KEY="<your-key>" \\
      python3 tools/acceptance_run.py --product "تمور" --market "Netherlands" \\
      --hs 080410 --own-price 9.0

بلا شبكة/مفتاح لا يعمل (بحث حيّ يكلّف ~$1) — هذه البيئة الهرمِتية ليست
مكانه؛ شغّله على Railway الحيّة. المعايير في docs/ACCEPTANCE_R1.md.

المكتبات: stdlib فقط (urllib/json/zipfile/re) — لا تبعيات، انسجاماً مع
قاعدة المستودع (stdlib-first). الدوال النقية (استخراج نص docx + مسح
المصطلحات) قابلة للاستيراد والاختبار هرمِتياً.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import zipfile

# ── المصطلحات المحظورة على مخرَج العميل (تِلِمِتري + الخمس الحرفية) ──────────
# مطابقة تُطبَّق على نص docx العميل الحيّ — البند 1.2/R4 في قائمة القبول.
FORBIDDEN_TERMS: list[tuple[str, str]] = [
    ("mission", r"بعث(?:ة|ات)|\bmissions?\b"),
    ("status", r"\bstatus\b"),
    ("successful", r"ناجحة|نجحت|\bsuccessful\b"),
    ("run", r"تشغيلة|\brun\b"),
    ("declared_gap", r"فجوة معلنة|فجوات معلنة"),
    ("tool_name", r"comtrade_imports|comtrade_competitors|worldbank_indicator|"
                  r"wits_tariff|trends_interest|trends_context|faostat_supply|"
                  r"web_search|gdelt_news|openalex_search|channels_importers|"
                  r"lookup_reference|eurostat_eu_signals"),
    ("agent_role", r"المحلل الشامل|كاتب التقرير|LLMMissionAgent|LLMAgent"),
    ("citation_plumbing", r"\bdatapoint\b|\bdp\d+\b"),
    ("algorithm_language", r"\bverdict\b|\bconfidence\b|\bscore\b|الدرجة الرقمية"),
    # الخمس الحرفية من تمرير النثر (PR-C0) — يجب ألّا تعود حيّةً:
    ("calque_wholesale_ref", r"سعر جملة مرجعي"),
    ("calque_comtrade_ar", r"كومتريد"),
    ("calque_landed_cost", r"تكلفة\s+هبوط"),
    ("calque_derivation", r"طريقة الاشتقاق"),
    ("calque_normalized", r"مطبَّع(?:ةً|ة|اً|ًا)?\s+لكل"),
]


def extract_docx_text(path: str) -> str:
    """نص docx كاملاً (فقرات + خلايا) عبر stdlib — docx حزمة zip، والنص في
    word/document.xml داخل وسوم <w:t>. لا python-docx (تبعية اختيارية)."""
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", "replace")
    # كل <w:t>…</w:t> نص مرئي؛ الفواصل بين الفقرات لا تهمّ للمسح.
    parts = re.findall(r"<w:t[^>]*>(.*?)</w:t>", xml, re.S)
    text = " ".join(parts)
    # فكّ كيانات XML الأساسية.
    for a, b in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                 ("&quot;", '"'), ("&#39;", "'")):
        text = text.replace(a, b)
    return text


def scan_forbidden(text: str) -> list[str]:
    """أرجع كل مصطلح محظور ظهر في النص — للفحص الآلي للبند 1.2/R4."""
    hits = []
    for label, pat in FORBIDDEN_TERMS:
        m = re.search(pat, text or "")
        if m:
            hits.append(f"{label}: «{m.group(0)}»")
    return hits


# ── عميل HTTP بسيط (stdlib) ───────────────────────────────────────────────

class Api:
    def __init__(self, base: str, key: str):
        self.base = base.rstrip("/")
        self.key = key

    def _req(self, method: str, path: str, body: dict | None = None,
             timeout: int = 180):
        url = self.base + path
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("X-API-Key", self.key)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read(), dict(resp.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read(), dict(e.headers or {})

    def json(self, method: str, path: str, body: dict | None = None,
             timeout: int = 180):
        code, raw, _ = self._req(method, path, body, timeout)
        try:
            return code, json.loads(raw.decode("utf-8"))
        except Exception:  # noqa: BLE001
            return code, {"_raw": raw.decode("utf-8", "replace")}

    def bytes(self, path: str, timeout: int = 180):
        return self._req("GET", path, None, timeout)  # (code, raw, headers)


def _save(folder: str, name: str, data) -> str:
    p = os.path.join(folder, name)
    mode = "wb" if isinstance(data, (bytes, bytearray)) else "w"
    with open(p, mode, encoding=None if "b" in mode else "utf-8") as f:
        f.write(data)
    return p


def _count_missions(result: dict) -> tuple[int, int, list[str]]:
    """عدّ البعثات التي أعادت بيانات حقيقية مقابل فجوات/فشل — البند 5.1.
    دفاعي: يبحث في deep_research.missions (findings غير فارغة = بيانات)."""
    dr = (result.get("deep_research")
          or (result.get("view") or {}).get("deep_research") or {})
    missions = dr.get("missions") or {}
    real, gaps = 0, []
    for key, rep in missions.items():
        if not isinstance(rep, dict):
            continue
        findings = rep.get("findings")
        failed = rep.get("failed")
        has_data = bool(findings) and not failed
        if has_data:
            real += 1
        else:
            gaps.append(key)
    return real, len(missions), gaps


def main() -> int:
    ap = argparse.ArgumentParser(description="تشغيلة قبول R1 الحيّة")
    ap.add_argument("--product", default="تمور")
    ap.add_argument("--market", default="Netherlands")
    ap.add_argument("--hs", default="080410")
    ap.add_argument("--own-price", type=float, default=9.0)
    ap.add_argument("--base", default=os.environ.get("SILK_API_BASE", ""))
    ap.add_argument("--key", default=os.environ.get("SILK_API_KEY", ""))
    ap.add_argument("--poll-interval", type=int, default=15)
    ap.add_argument("--timeout", type=int, default=2400, help="ثوانٍ حتى الاكتمال")
    ap.add_argument("--outdir", default="")
    a = ap.parse_args()

    if not a.base or not a.key:
        print("خطأ: مرّر --base/--key أو صدّر SILK_API_BASE/SILK_API_KEY",
              file=sys.stderr)
        return 2

    # مجلّد المخرجات (طابع زمني من ساعة النظام — على جهازك، لا هذه البيئة).
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = a.outdir or os.path.join("acceptance_out", stamp)
    os.makedirs(out, exist_ok=True)
    print(f"→ مجلّد المخرجات: {out}")

    api = Api(a.base, a.key)
    summary: list[str] = [f"# قبول R1 — {a.product} × {a.market} (HS {a.hs})",
                          f"القاعدة: {a.base}", f"الوقت: {stamp}", ""]

    # ٠. صحّة النظام
    code, health = api.json("GET", "/health")
    _save(out, "health.json", json.dumps(health, ensure_ascii=False, indent=2))
    ready = bool(health.get("research_ready"))
    summary.append(f"[0] /health: research_ready={ready} (HTTP {code})")
    if not ready:
        summary.append("  ⚠ research_ready=false — قد تفشل التشغيلة؛ متابعة على مسؤوليتك")

    # ١. إطلاق البحث (async — لا تقطعه بوّابة عكسية)
    req_body = {"product": a.product, "market": a.market, "hs_code": a.hs,
                "own_price": a.own_price, "async_run": True, "persist": True}
    _save(out, "request.json", json.dumps(req_body, ensure_ascii=False, indent=2))
    code, launched = api.json("POST", "/research", req_body)
    if code not in (200, 202):
        _save(out, "launch_error.json",
              json.dumps(launched, ensure_ascii=False, indent=2))
        summary.append(f"[1] فشل الإطلاق HTTP {code}: {launched}")
        _save(out, "SUMMARY.txt", "\n".join(summary))
        print("\n".join(summary))
        return 1
    aid = launched.get("analysis_id")
    summary.append(f"[1] أُطلقت التشغيلة: analysis_id={aid} (HTTP {code})")
    print(f"→ analysis_id={aid} — استطلاع كل {a.poll_interval}s حتى الاكتمال…")

    # ٢. استطلاع حتى الاكتمال
    t0, status = time.time(), "running"
    last = {}
    while time.time() - t0 < a.timeout:
        code, st = api.json("GET", f"/research/{aid}/status")
        status = st.get("status", "unknown")
        done = st.get("missions_completed", "?")
        total = st.get("missions_total", "?")
        print(f"  … status={status} missions={done}/{total} "
              f"(+{int(time.time()-t0)}s)")
        last = st
        if status in ("completed", "failed", "error"):
            break
        time.sleep(a.poll_interval)
    _save(out, "status_final.json", json.dumps(last, ensure_ascii=False, indent=2))
    summary.append(f"[2] الحالة النهائية: {status} "
                   f"بعد {int(time.time()-t0)}s")
    if status != "completed":
        summary.append("  ⚠ لم تكتمل — استخدم resume لا إعادة الإطلاق")
        _save(out, "SUMMARY.txt", "\n".join(summary))
        print("\n".join(summary))
        return 1

    # ٣. النتيجة الكاملة
    code, result = api.json("GET", f"/analyses/{aid}", timeout=300)
    _save(out, "result.json", json.dumps(result, ensure_ascii=False, indent=2))

    # ٤. مشتقّات التقرير
    for path, fname in (
        (f"/analyses/{aid}/report.docx", "client_report.docx"),
        (f"/analyses/{aid}/report.docx?internal=1", "operator_report.docx"),
        (f"/analyses/{aid}/report.md", "report.md"),
        (f"/analyses/{aid}/brief", "brief.txt"),
    ):
        c, raw, _ = api.bytes(path, timeout=300)
        if c == 200:
            _save(out, fname, raw)
        else:
            summary.append(f"  ⚠ {fname}: HTTP {c}")

    # ٥. ثلاثة أسئلة دردشة + سؤال ضبط سلبي
    questions = [
        "ما حجم واردات هولندا من التمور وكم نموّها؟",
        "مَن أبرز المنتجات أو العلامات المنافسة وبأي أسعار؟",
        "ما بوابة الأهلية التنظيمية الأولى للدخول؟",
        "ما عدد سكان اليابان؟",   # ضبط سلبي — يجب أن يُعلَن خارج الدراسة
    ]
    chat = []
    for q in questions:
        c, ans = api.json("POST", f"/analyses/{aid}/ask", {"question": q},
                          timeout=180)
        chat.append({"question": q, "http": c, "response": ans})
        print(f"  ask «{q[:30]}…» → HTTP {c}")
    _save(out, "chat_answers.json", json.dumps(chat, ensure_ascii=False, indent=2))
    summary.append(f"[5] الدردشة: {len(questions)} أسئلة محفوظة "
                   "(راجِع الإرضاء + سؤال الضبط يدوياً)")

    # ٦. فحوص آلية على المخرَج الحيّ
    econ = result.get("data_economics") or {}
    cost_usd = econ.get("cost_usd_estimate")
    unpriced = econ.get("cost_usd_by_model") and econ.get("cost_unpriced_models")
    real, total_m, gaps = _count_missions(result)
    summary.append("")
    summary.append("── فحوص آلية ──")
    summary.append(f"[6] التكلفة الفعلية: ${cost_usd} (خط الأساس ~$1)")
    if econ.get("cost_unpriced_models"):
        summary.append(f"  ⚠ نماذج غير مسعّرة: {econ['cost_unpriced_models']}")
    summary.append(f"[5] تغطية البعثات: {real}/{total_m} أعادت بيانات حقيقية "
                   f"(عتبة ≥8)  |  فجوات: {', '.join(gaps) or 'لا شيء'}")

    client_docx = os.path.join(out, "client_report.docx")
    if os.path.exists(client_docx):
        try:
            txt = extract_docx_text(client_docx)
            hits = scan_forbidden(txt)
            if hits:
                summary.append(f"[1.2/R4] ✗ مصطلحات محظورة على docx العميل: "
                               f"{'؛ '.join(hits[:10])}")
            else:
                summary.append("[1.2/R4] ✓ صفر مصطلح محظور على docx العميل الحيّ")
        except Exception as e:  # noqa: BLE001
            summary.append(f"[1.2/R4] تعذّر مسح docx: {e}")

    # حكم بوابة الجودة إن ظهر
    qg = ((result.get("view") or {}).get("deep_research") or {}).get("quality_gate")
    if qg:
        summary.append(f"[R10] بوابة الجودة: {qg.get('verdict')}")

    summary.append("")
    summary.append("راجِع docs/ACCEPTANCE_R1.md لبقيّة البنود اليدوية "
                   "(1.1/1.3/1.4، الموقع السعري، مسطرة العشرة معايير).")
    text = "\n".join(summary)
    _save(out, "SUMMARY.txt", text)
    print("\n" + text)
    print(f"\n✓ تمّ — كل المخرجات في {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
