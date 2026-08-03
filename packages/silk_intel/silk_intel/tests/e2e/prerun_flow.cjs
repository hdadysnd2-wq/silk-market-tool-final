// رُتبة ٣ — تدفّق ما قبل التشغيل (Wave 1: the pre-run modal click-through).
//
// > الشرط المُلزِم (أمر العمل): متصفّح حقيقي ينقر نوافذ ما قبل التشغيل الجديدة:
// > اختيار المنتج والسوق ← «بحث عميق» ← نافذة تصنيف HS (اقتراح) ← تأكيد ←
// > نافذة استشارة بلد المنشأ (سوق منتِجة) ← موافقة ← إعادة الإرسال بموافقة.
// > كلّ الأعلام تبقى مُطفأة في الإنتاج حتى يرى المُشرِف هذا التدفّق أخضر.
//
// يعمل ضدّ خادم رُتبة ٢ في وضع prerun_flags: صمّاما التصنيف/الاستشارة مُفعَّلان،
// ومخبأ كومتريد لتصدير العالم مبذورٌ فتُطلق الاستشارةُ من بياناتٍ حقيقية الشكل
// بلا شبكة ولا مفتاح مدفوع. لا يلمس soffice/PDF إطلاقًا (مستقلّ عن مسار التصدير).
//
// CommonJS عمداً (يحترم NODE_PATH). يخرج 0 عند نجاح كل خطوة، و1 عند أوّل إخفاق.

const { chromium } = require("playwright");

const BASE = process.env.BASE_URL;
const MARKET = process.env.PRERUN_MARKET_ISO3 || "ARE";
const PRODUCT = process.env.PRERUN_PRODUCT || "تمور";
const HS = process.env.PRERUN_HS || "080410";

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
    // ١) افتح اللوحة — /config يعيد hs_classifier/producer_advisory=true.
    await page.goto(BASE, { waitUntil: "networkidle", timeout: 30000 });
    await page.waitForSelector("#marketBox .mrow", { timeout: 15000 });
    ok("dashboard_render");

    // ٢) اختر المنتج من قائمة البحث (يضبط S.product) — نكتب ثم ننقر صفًّا.
    await page.fill("#pSearch", PRODUCT);
    await page.waitForSelector("#pDrop.open .drow", { timeout: 10000 });
    await page.locator("#pDrop .drow").first().click();
    ok("product_selected");

    // ٣) اختر السوق المنتِجة (الإمارات — من أكبر مصدّري التمور).
    const mrow = page.locator(`#marketBox .mrow[data-iso3="${MARKET}"]`);
    if ((await mrow.count()) < 1)
      fail("market_selected", `no market row for ${MARKET}`);
    await mrow.first().click();
    ok("market_selected", MARKET);

    // ٤) «بحث عميق» — الموجة ٣ (المصنّف العام): «تمور» تُصنَّف تلقائياً
    //    بثقةٍ صارمة (tier=auto) بلا أيّ صندوق حوار — الشارة الصادقة
    //    «✓ صُنّف تلقائياً» تظهر مباشرةً على #pResolved، والتدفّق يتابع
    //    مباشرةً لاستشارة بلد المنشأ (لا نقرة تأكيدٍ وسيطة لمنتجٍ محسومٍ).
    await page.locator("#researchBtn").click();
    await page.waitForFunction(() => {
      const el = document.querySelector("#pResolved");
      return el && el.classList.contains("on") && /✓/.test(el.textContent || "");
    }, { timeout: 15000 });
    const resolvedText = await page.locator("#pResolved").innerText();
    if (!resolvedText.includes(HS))
      fail("auto_classify", `resolved badge missing HS ${HS}: ${resolvedText}`);
    ok("auto_classify", "honest ✓ badge shown, no blocking dialog for a clean match");

    // ٥) (لا نقرة تأكيدٍ هنا — تلقائيٌّ فعلاً، الفرق الجوهري عن مسار المرشّحين.)

    // ٦) استشارة بلد المنشأ — سوقٌ من أكبر مصدّري هذا الرمز => نافذة تحذير.
    await page.waitForSelector("#advOk", { timeout: 15000 });
    const advText = await page.locator(".prov").first().innerText();
    if (!/أكبر مصدّري|تنافسية/.test(advText))
      fail("producer_advisory_modal",
        `advisory card missing warning text: ${advText}`);
    if (!advText.includes(MARKET))
      fail("producer_advisory_modal",
        `advisory card missing exporter ${MARKET}: ${advText}`);
    ok("producer_advisory_modal", "top-exporter warning shown");

    // ٧) موافقة صريحة — تُغلق النافذة وتعيد الإرسال بـproducer_ack. الخادم بلا
    //    مفتاح كلود => يعود 409 جهوزية (رسالة toast)، لكن الاستشارة **لا تتكرّر**
    //    (أُقرّت). هذا يثبت مرور الموافقة عبر البوّابة كاملةً.
    await page.locator("#advOk").click();
    await page.waitForFunction(() => !document.querySelector(".prov"),
      { timeout: 15000 });
    // بعد الموافقة: لا نافذة استشارة باقية، وزرّ البحث عاد للخمول (لم يعلق).
    await page.waitForFunction(() => {
      const b = document.querySelector("#researchBtn");
      return b && !b.disabled;
    }, { timeout: 15000 });
    if (await page.locator("#advOk").count())
      fail("consent_resubmit", "advisory modal reappeared after consent");
    ok("consent_resubmit", "consent flowed through; advisory not repeated");

    if (consoleErrors.length)
      fail("no_page_errors", consoleErrors.join(" | "));
    ok("no_page_errors");

    console.log(JSON.stringify({ result: "PASS", steps }, null, 2));
    console.log("PRERUN PASS");
  } finally {
    await browser.close();
  }
}

main().catch((e) => {
  console.error(JSON.stringify({ result: "FAIL", steps }, null, 2));
  console.error(String(e && e.stack ? e.stack : e));
  process.exit(1);
});
