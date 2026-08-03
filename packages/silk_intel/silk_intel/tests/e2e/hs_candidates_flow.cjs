// رُتبة ٣ — صندوق حوار مرشّحي HS (الموجة ٣: المصنّف العام، systemic fix).
//
// > الطلب: منتجٌ ضعيف التمثيل/غامضٌ في بذرتنا الحتمية («عود معطر» — منتجٌ
// > غير معتادٍ من عائلة حادثة الكويت، LESSONS ٣٩) => صندوقُ حوارٍ حاجبٌ
// > بمرشّحين فعليّين، لا اختلاقٌ صامت. اختيار مرشّح يُتابع التدفّق.
// >
// > (بطل الحادثة الأصلية «زبدة الفول السوداني» عاد يُحسَم تلقائياً للرمز
// > الصحيح 200811 بعد إصلاح البذرة — طلب المالك 2026-07-23؛ صار قفلَ auto
// > في `hs_tier_family_flow.cjs`، فلم يعُد صالحاً مثالاً على منتجٍ مُعلَّم.)
//
// خادم رُتبة ٢ في وضع prerun_flags (SILK_HS_CLASSIFIER=1) لكن **بلا مفتاح
// كلود** (يُنزَع عمداً في كل e2e) — المرشّحون هنا حتميّون (بذرة CSV) لا
// عامّون بمساعدة نموذج؛ إثبات المسار العام الكامل بمساعدة النموذج هو
// بوّابة المالك المدفوعة (LAW §2، الدلو الثاني) لا هذا الاختبار الهرمتي.
// اسم المنتج يُضبَط عبر خطّاف اختبارٍ (`window.__silkTestSetProduct`) بدل
// نقر صفّ فهرسٍ.

const { chromium } = require("playwright");

const BASE = process.env.BASE_URL;
const MARKET = process.env.PRERUN_MARKET_ISO3 || "ARE";
const PRODUCT = process.env.HS_CANDIDATES_PRODUCT || "عود معطر";

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

    // ١) منتجٌ غائبٌ عن الفهرس عمداً — يُضبَط عبر خطّاف اختبار، لا نقر صفٍّ.
    await page.evaluate((name) => window.__silkTestSetProduct(name), PRODUCT);
    ok("product_set_via_hook", PRODUCT);

    // ٢) اختر أيّ سوق (لا علاقة لهذا الاختبار باستشارة بلد المنشأ).
    const mrow = page.locator(`#marketBox .mrow[data-iso3="${MARKET}"]`);
    const anyMrow = (await mrow.count()) ? mrow.first()
      : page.locator("#marketBox .mrow").first();
    await anyMrow.click();
    ok("market_selected");

    // ٣) «بحث عميق» → المُحلِّل الحتمي يُعلِّم الرمز (لا تلقائي صارم) => صندوقُ
    //    حوار مرشّحين حاجب — لا «✓ صُنّف تلقائياً» على منتجٍ غير محسوم.
    await page.locator("#researchBtn").click();
    await page.waitForSelector(".prov", { timeout: 15000 });
    const dialogText = await page.locator(".prov").first().innerText();
    if (!/تأكيد رمز HS/.test(dialogText))
      fail("candidates_modal", `dialog missing heading: ${dialogText}`);
    if (/صُنّف تلقائياً/.test(dialogText))
      fail("candidates_modal",
        `dialog must never show the auto-classified checkmark: ${dialogText}`);
    ok("candidates_modal", "blocking dialog shown, no auto-badge");

    // ٤) لا بدّ من مرشّحٍ واحدٍ فعليّ على الأقل (لا صندوقٌ فارغ صامت).
    const candCount = await page.locator(".hsCand").count();
    if (candCount < 1)
      fail("candidates_present", "no candidate buttons rendered");
    ok("candidates_present", `${candCount} candidate(s) shown`);

    // ٥) اختر أوّل مرشّح — يُغلق الصندوق ويضبط الرمز المؤكَّد فعلياً.
    const chosenHs = await page.locator(".hsCand").first().getAttribute("data-hs");
    await page.locator(".hsCand").first().click();
    await page.waitForFunction(() => !document.querySelector(".prov"),
      { timeout: 15000 });
    ok("candidate_selected", chosenHs || "");

    // ٦) الشارة تعكس الاختيار الفعلي (تأكيدٌ يدويٌّ بنقرة، لا تلقائي).
    await page.waitForFunction((hs) => {
      const el = document.querySelector("#pResolved");
      return el && el.classList.contains("on") && el.textContent.includes(hs);
    }, chosenHs, { timeout: 15000 });
    ok("resolved_badge_matches_choice");

    if (consoleErrors.length)
      fail("no_page_errors", consoleErrors.join(" | "));
    ok("no_page_errors");

    console.log(JSON.stringify({ result: "PASS", steps }, null, 2));
    console.log("HSCAND PASS");
  } finally {
    await browser.close();
  }
}

main().catch((e) => {
  console.error(JSON.stringify({ result: "FAIL", steps }, null, 2));
  console.error(String(e && e.stack ? e.stack : e));
  process.exit(1);
});
