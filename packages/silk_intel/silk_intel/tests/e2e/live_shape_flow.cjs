// رُتبة ٣ — متصفّح حقيقي (rung 3: the real-browser flow).
//
// > القاعدة الجديدة (تأكيد المالك آخِراً لا أوّلاً). هذا التدفّق ينقر الواجهة
// > الفعلية بـchromium (headless) ضدّ خادم رُتبة ٢: افتح اللوحة ← انقر عنصر
// > الشريط الجانبي ← يُعرَض التقرير ← انقر تصدير Word ← تأكّد نزول .docx غير
// > فارغ ← انقر تصدير Markdown ← تأكّد محتوى حقيقي لا القالب الفارغ ← تأكّد
// > صندوق التقدّم (صفّ «جارٍ التشغيل…» + استئناف). هذا بالضبط كان سيلتقط
// > خطأَي التصدير والشريط الجانبي الميت قبل أن يراهما المالك.
//
// CommonJS (.cjs) عمداً: `require` يحترم NODE_PATH (حيث تُثبَّت playwright
// العمومية) بينما `import` (ESM) لا يفعل. يُشغَّل من مُغلِّف pytest
// (tests/test_rung3_playwright_e2e.py) الذي يُقلِع خادم رُتبة ٢ ويمرّر
// BASE_URL/COMPLETED_ID/RUNNING_ID عبر البيئة. المتصفّح من /opt/pw-browsers.
//
// يخرج 0 عند نجاح كل خطوة، و1 عند أوّل إخفاق (مع سبب واضح على stderr).

const { chromium } = require("playwright");
const fs = require("node:fs");

const BASE = process.env.BASE_URL;
const COMPLETED_ID = Number(process.env.COMPLETED_ID);
const RUNNING_ID = Number(process.env.RUNNING_ID);

if (!BASE || !COMPLETED_ID) {
  console.error("MISSING BASE_URL/COMPLETED_ID env");
  process.exit(2);
}

const steps = [];
function ok(name, detail) { steps.push({ name, ok: true, detail: detail || "" }); }
function fail(name, detail) {
  steps.push({ name, ok: false, detail: detail || "" });
  throw new Error(`STEP FAILED: ${name} — ${detail || ""}`);
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ acceptDownloads: true });
  const page = await context.newPage();
  const consoleErrors = [];
  page.on("pageerror", (e) => consoleErrors.push(String(e)));

  try {
    // ١) افتح اللوحة — الصفحة تُحمَّل والشريط الجانبي يُملأ من GET /analyses.
    await page.goto(BASE, { waitUntil: "networkidle", timeout: 30000 });
    await page.waitForSelector("#histList .hist", { timeout: 15000 });
    ok("dashboard_render");

    // ٢) صندوق التقدّم — الصفّ الجارٍ يعرض شارة «جارٍ التشغيل…» + زرّ استئناف.
    const runningRow = page.locator(`#histList .hist[data-id="${RUNNING_ID}"]`);
    if ((await runningRow.count()) < 1)
      fail("progress_box", `no sidebar row for running id=${RUNNING_ID}`);
    const runningText = await runningRow.first().innerText();
    if (!/جارٍ التشغيل/.test(runningText))
      fail("progress_box", `running row missing progress badge: ${runningText}`);
    const resumeBtn = runningRow.locator("[data-resume-id]");
    if ((await resumeBtn.count()) < 1)
      fail("progress_box", "running row missing resume affordance");
    ok("progress_box", "running badge + resume present");

    // ٣) انقر عنصر الشريط الجانبي المكتمل — يجب أن يُعرَض التقرير الكامل.
    const completedRow = page.locator(
      `#histList .hist[data-id="${COMPLETED_ID}"]`);
    if ((await completedRow.count()) < 1)
      fail("sidebar_click", `no sidebar row for completed id=${COMPLETED_ID}`);
    await completedRow.first().click();
    // اللوحة تُبنى من GET /analyses/{id} — انتظر ظهور نصّ التقرير الحقيقي.
    await page.waitForFunction(
      () => {
        const b = document.querySelector("#boardBody");
        return b && /HHI/.test(b.textContent || "");
      },
      { timeout: 15000 },
    );
    const boardText = await page.locator("#boardBody").innerText();
    if (!/التقرير الكامل/.test(boardText))
      fail("sidebar_click", "board did not render the full report heading");
    if (/with_research/.test(boardText))
      fail("sidebar_click", "board leaked empty /analyze template markers");
    ok("sidebar_click", "report rendered from stored analysis");

    // ٣ب) زرّ التعبئة الرجعية لبيانات المستوردين (تقرير محفوظ قديم) — انقره،
    // تأكّد تعطيله أثناء الطلب ثم عودته بنتيجة عربية غير فارغة. المكشطة غير
    // مُهيَّأة في هذه البيئة ⇒ تعطيل نظيف (enriched=false مع إبلاغ صريح)، لكن
    // الزرّ يجب أن يكون حاضراً وينفّذ الدورة كاملة (تقدّم ← نتيجة).
    const enrichBtn = page.locator("#enrichLeadsBtn");
    if ((await enrichBtn.count()) < 1)
      fail("enrich_leads_backfill",
        "no backfill enrich-leads button on stored research report");
    await enrichBtn.click();
    await page.waitForFunction(
      () => {
        const b = document.querySelector("#enrichLeadsBtn");
        const s = document.querySelector("#enrichLeadsStatus");
        return b && !b.disabled && s && (s.textContent || "").trim().length > 0;
      },
      { timeout: 25000 },
    );
    const enrichStatus = await page.locator("#enrichLeadsStatus").innerText();
    if (!enrichStatus.trim())
      fail("enrich_leads_backfill", "status stayed empty after click");
    ok("enrich_leads_backfill", enrichStatus.slice(0, 80));

    // ٤) تصدير PDF — المُسلَّم النهائي للعميل (§3): نقر #pdfBtn ينزّل ملفاً
    // بتوقيع %PDF غير فارغ. هذا المسار الأساسي (اتفاق المالك: PDF أوّلاً).
    const pdfPromise = page.waitForEvent("download", { timeout: 30000 });
    await page.locator("#pdfBtn").click();
    const pdfDl = await pdfPromise;
    const pdfPath = await pdfDl.path();
    const pdfBuf = fs.readFileSync(pdfPath);
    if (pdfBuf.length < 1000)
      fail("pdf_export", `downloaded pdf too small: ${pdfBuf.length} bytes`);
    // "%PDF" = 0x25 0x50 0x44 0x46
    if (!(pdfBuf[0] === 0x25 && pdfBuf[1] === 0x50 &&
          pdfBuf[2] === 0x44 && pdfBuf[3] === 0x46))
      fail("pdf_export",
        "downloaded file is not a PDF (no %PDF header) — converter likely absent (503)");
    const pdfName = pdfDl.suggestedFilename();
    if (!/\.pdf$/.test(pdfName))
      fail("pdf_export", `unexpected pdf filename: ${pdfName}`);
    ok("pdf_export", `${pdfBuf.length} bytes, ${pdfName}`);

    // ٤ب) تصدير Word — المسار الثانوي/التشغيلي (نسخة قابلة للتحرير): نقر
    // #wordBtn ينزّل .docx غير فارغ (توقيع ZIP «PK»).
    const dlPromise = page.waitForEvent("download", { timeout: 20000 });
    await page.locator("#wordBtn").click();
    const download = await dlPromise;
    const dlPath = await download.path();
    const buf = fs.readFileSync(dlPath);
    if (buf.length < 1000)
      fail("word_export", `downloaded docx too small: ${buf.length} bytes`);
    if (!(buf[0] === 0x50 && buf[1] === 0x4b)) // "PK"
      fail("word_export", "downloaded file is not a ZIP/docx (no PK signature)");
    const suggested = download.suggestedFilename();
    if (!/\.docx$/.test(suggested))
      fail("word_export", `unexpected filename: ${suggested}`);
    ok("word_export", `${buf.length} bytes, ${suggested}`);

    // ٥) تصدير Markdown — نقر #mdBtn يفتح نافذة بمحتوى حقيقي لا القالب الفارغ.
    const popupPromise = page.waitForEvent("popup", { timeout: 20000 });
    await page.locator("#mdBtn").click();
    const popup = await popupPromise;
    await popup.waitForFunction(
      () => {
        const pre = document.querySelector("pre");
        return pre && (pre.textContent || "").length > 100;
      },
      { timeout: 15000 },
    );
    const md = await popup.locator("pre").innerText();
    if (!/HHI/.test(md) || !/EU 2017\/625/.test(md))
      fail("md_export", "markdown missing the real narrative (HHI / EU regs)");
    if (/with_research/.test(md) || /0 أسواق مرشّحة/.test(md))
      fail("md_export", "markdown is the empty /analyze template, not real content");
    ok("md_export", `${md.length} chars of real narrative`);

    if (consoleErrors.length)
      fail("no_page_errors", consoleErrors.join(" | "));
    ok("no_page_errors");

    console.log(JSON.stringify({ result: "PASS", steps }, null, 2));
    console.log("RUNG3 PASS");
  } finally {
    await browser.close();
  }
}

main().catch((e) => {
  console.error(JSON.stringify({ result: "FAIL", steps }, null, 2));
  console.error(String(e && e.stack ? e.stack : e));
  process.exit(1);
});
