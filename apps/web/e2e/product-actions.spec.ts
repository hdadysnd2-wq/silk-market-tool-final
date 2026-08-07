import { test, expect, type Route } from "@playwright/test";
import { fakeToken, PRODUCT_REPORT } from "./fixtures";

const BASE = "http://localhost:3100";

const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, json: body });

// A product whose HS code is already confirmed, with a second candidate on hand
// so the operator can change their mind. A confirmed product shows the "Change
// code" (override) button instead of "Confirm code".
function confirmedProduct() {
  return {
    id: "prod-1",
    factory_id: "fac-1",
    name_ar: "تمور فاخرة",
    name_en: "Premium Dates",
    description_ar: null,
    description_en: "Saudi Medjool dates",
    image_url: null,
    price_min: 10,
    price_max: 20,
    currency: "USD",
    hs_code: "080410",
    hs_candidates: [
      {
        code: "080410",
        confidence: 0.92,
        rationale: "Dates",
        description_en: "Dates, fresh or dried",
        description_ar: "تمور",
        in_catalogue: true,
      },
      {
        code: "080420",
        confidence: 0.31,
        rationale: "Figs",
        description_en: "Figs, fresh or dried",
        description_ar: "تين",
        in_catalogue: true,
      },
    ],
    hs_confirmed_by_user: true,
    classification_status: "classified",
    created_at: "2026-01-01T00:00:00Z",
  };
}

test("overriding a confirmed HS code posts the newly chosen candidate", async ({
  page,
  context,
}) => {
  await context.addCookies([{ name: "silk_token", value: fakeToken(), url: BASE }]);
  await page.route(/\/api\/v1\//, (route) => json(route, []));
  await page.route(/\/api\/v1\/products\/prod-1$/, (route) => json(route, confirmedProduct()));

  let overridden: unknown = null;
  await page.route(/\/api\/v1\/products\/prod-1\/hs-code$/, (route) => {
    overridden = route.request().postDataJSON();
    return json(route, confirmedProduct());
  });

  await page.goto("/en/products/prod-1");

  // The confirmed product offers "Change code", not "Confirm code".
  const change = page.getByRole("button", { name: "Change code" });
  await expect(change).toBeVisible();
  await expect(page.getByRole("button", { name: "Confirm code" })).toHaveCount(0);

  // Pick the runner-up candidate, then commit the override.
  await page.getByRole("button", { name: /Figs, fresh or dried/ }).click();
  const [request] = await Promise.all([
    page.waitForRequest(
      (r) => r.url().endsWith("/api/v1/products/prod-1/hs-code") && r.method() === "PUT",
    ),
    change.click(),
  ]);
  expect(request.postDataJSON()).toMatchObject({ hs_code: "080420" });
  expect(overridden).toMatchObject({ hs_code: "080420" });
});

test("the report screen downloads the HTML export", async ({ page, context }) => {
  await context.addCookies([{ name: "silk_token", value: fakeToken(), url: BASE }]);
  await page.route(/\/api\/v1\//, (route) => json(route, []));
  // The JSON report drives the screen; note this must not swallow report.html.
  await page.route(/\/api\/v1\/products\/prod-1\/report\?locale=/, (route) =>
    json(route, PRODUCT_REPORT),
  );
  // The download endpoint returns HTML, fetched as a Blob with the bearer token.
  let htmlRequested = false;
  await page.route(/\/api\/v1\/products\/prod-1\/report\.html/, (route) => {
    htmlRequested = true;
    return route.fulfill({ contentType: "text/html", body: "<html><body>report</body></html>" });
  });

  await page.goto("/en/products/prod-1/report");

  // Header + a summary tile confirm the report rendered from the mock.
  await expect(page.getByRole("heading", { name: "Export intelligence report" })).toBeVisible();
  await expect(page.getByText("Premium Dates")).toBeVisible();

  const download = page.getByRole("button", { name: "Download HTML" });
  await Promise.all([
    page.waitForRequest((r) => r.url().includes("/api/v1/products/prod-1/report.html")),
    download.click(),
  ]);
  expect(htmlRequested).toBe(true);
});

test("the executive report is the default Word download; the deep report stays a drill-down", async ({
  page,
  context,
}) => {
  await context.addCookies([{ name: "silk_token", value: fakeToken(), url: BASE }]);
  await page.route(/\/api\/v1\//, (route) => json(route, []));
  await page.route(/\/api\/v1\/products\/prod-1\/report\?locale=/, (route) =>
    json(route, PRODUCT_REPORT),
  );
  const DOCX_TYPE =
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
  let executiveRequested = false;
  let deepRequested = false;
  await page.route(/\/api\/v1\/products\/prod-1\/report\/executive/, (route) => {
    executiveRequested = true;
    return route.fulfill({ contentType: DOCX_TYPE, body: "PK-exec" });
  });
  await page.route(/\/api\/v1\/products\/prod-1\/report\.docx/, (route) => {
    deepRequested = true;
    return route.fulfill({ contentType: DOCX_TYPE, body: "PK-deep" });
  });

  await page.goto("/en/products/prod-1/report");
  await expect(page.getByText("Premium Dates")).toBeVisible();

  // Executive is the primary (default) deliverable.
  await Promise.all([
    page.waitForRequest((r) => r.url().includes("/report/executive")),
    page.getByRole("button", { name: "Executive report (Word)" }).click(),
  ]);
  expect(executiveRequested).toBe(true);

  // The deep report is NOT gone — it is the on-demand drill-down.
  await Promise.all([
    page.waitForRequest((r) => r.url().includes("/report.docx")),
    page.getByRole("button", { name: "Deep report (Word)" }).click(),
  ]);
  expect(deepRequested).toBe(true);
});
