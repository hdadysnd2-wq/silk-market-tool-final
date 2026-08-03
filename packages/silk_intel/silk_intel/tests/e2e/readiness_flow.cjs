// رُتبة ٣ — لوحة «جاهزية الدراسة» (Wave 1.5, family D: the readiness panel).
//
// > عائلة D (أمر العمل): كلُّ تدهورٍ معروفٍ **قبل الحجز** كسطر ✓/⚠/✗ في لوحةٍ
// > موحّدة، فلا يعرف المالك تدهورًا بعد الدفع. متصفّح حقيقي: اختيار المنتج
// > والسوق ← «بحث عميق» ← نافذة تصنيف ← تأكيد ← **لوحة الجاهزية** (سطر ⚠ لبلد
// > المنشأ من مخبأ مبذور) ← «أكمل الدراسة» ← إعادة إرسال بالموافقات الموحّدة.
//
// يعمل ضدّ خادم رُتبة ٢ في وضع readiness_panel (يُفعّل SILK_PRERUN_ADVISORIES
// إضافةً لصمّامات ما قبل التشغيل، ويبذر مخبأ التصدير). بلا شبكة/مفتاح/soffice.

const { chromium } = require("playwright");

const BASE = process.env.BASE_URL;
const MARKET = process.env.PRERUN_MARKET_ISO3 || "ARE";
const PRODUCT = process.env.PRERUN_PRODUCT || "تمور";

if (!BASE) { console.error("MISSING BASE_URL env"); process.exit(2); }

const steps = [];
function ok(name, detail) { steps.push({ name, ok: true, detail: detail || "" }); }
function fail(name, detail) {
  steps.push({ name, ok: false, detail: detail || "" });
  throw new Error(`STEP FAILED: ${name} — ${detail || ""}`);
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();
  const consoleErrors = [];
  page.on("pageerror", (e) => consoleErrors.push(String(e)));

  try {
    await page.goto(BASE, { waitUntil: "networkidle", timeout: 30000 });
    await page.waitForSelector("#marketBox .mrow", { timeout: 15000 });
    ok("dashboard_render");

    await page.fill("#pSearch", PRODUCT);
    await page.waitForSelector("#pDrop.open .drow", { timeout: 10000 });
    await page.locator("#pDrop .drow").first().click();
    const mrow = page.locator(`#marketBox .mrow[data-iso3="${MARKET}"]`);
    if ((await mrow.count()) < 1) fail("select", `no market row ${MARKET}`);
    await mrow.first().click();
    ok("product_market_selected");

    // «بحث عميق» — الموجة ٣: «تمور» تُصنَّف تلقائياً (tier=auto) بلا صندوق
    // حوار — الشارة الصادقة تكفي، ثم مباشرةً للوحة الجاهزية.
    await page.locator("#researchBtn").click();
    await page.waitForFunction(() => {
      const el = document.querySelector("#pResolved");
      return el && el.classList.contains("on") && /✓/.test(el.textContent || "");
    }, { timeout: 15000 });

    // لوحة الجاهزية — تظهر بدل نافذة الاستشارة المنفردة، بسطر ⚠ واحد على الأقل.
    await page.waitForSelector("#rdGo", { timeout: 15000 });
    const panelText = await page.locator(".prov").first().innerText();
    if (!/جاهزية الدراسة/.test(panelText))
      fail("readiness_panel", `panel missing title: ${panelText}`);
    if (!/⚠/.test(panelText))
      fail("readiness_panel", `panel missing any advisory line: ${panelText}`);
    if (!/بلد المنشأ/.test(panelText))
      fail("readiness_panel", `panel missing producer-country line: ${panelText}`);
    // الزرّ مُفعَّل (لا حاجب — كله ⚠/✓، لا ✗).
    if (await page.locator("#rdGo[disabled]").count())
      fail("readiness_panel", "run button disabled though no blocker present");
    ok("readiness_panel", "checklist shown before confirm");

    // «أكمل الدراسة» — الموافقة الموحّدة تعبر البوّابة (الخادم بلا مفتاح => 409،
    // لكن اللوحة لا تتكرّر) — يثبت مرور الموافقات.
    await page.locator("#rdGo").click();
    await page.waitForFunction(() => !document.querySelector(".prov"),
      { timeout: 15000 });
    await page.waitForFunction(() => {
      const b = document.querySelector("#researchBtn");
      return b && !b.disabled;
    }, { timeout: 15000 });
    if (await page.locator("#rdGo").count())
      fail("consent_resubmit", "readiness panel reappeared after consent");
    ok("consent_resubmit", "unified consent flowed through");

    if (consoleErrors.length) fail("no_page_errors", consoleErrors.join(" | "));
    ok("no_page_errors");

    console.log(JSON.stringify({ result: "PASS", steps }, null, 2));
    console.log("READINESS PASS");
  } finally {
    await browser.close();
  }
}

main().catch((e) => {
  console.error(JSON.stringify({ result: "FAIL", steps }, null, 2));
  console.error(String(e && e.stack ? e.stack : e));
  process.exit(1);
});
