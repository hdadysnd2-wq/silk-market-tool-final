import { test, expect, type Route } from "@playwright/test";
import { fakeToken, VERIFIED_ACCOUNT, BUYER_MATCH, CAMPAIGN, EMAILS } from "./fixtures";

const BASE = "http://localhost:3100";

// One product that gains a confirmed HS code partway through the journey.
function product(confirmed: boolean) {
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
    hs_confirmed_by_user: confirmed,
    classification_status: confirmed ? "classified" : "pending",
    created_at: "2026-01-01T00:00:00Z",
  };
}

const ANALYSIS = {
  id: "an-1",
  product_id: "prod-1",
  product_name: "Premium Dates",
  status: "complete",
  deepen: false,
  created_at: "2026-01-01T00:00:00Z",
  rankings: [
    { rank: 1, importer_iso3: "IND", market_iso2: "IN", year: 2024, import_usd: 5_000_000, yoy_growth: 0.12, cagr_3y: 0.08, screen_score: 90, is_transit_hub: false, is_mirror: false, tags: null, stage: 1 },
    { rank: 2, importer_iso3: "NLD", market_iso2: "NL", year: 2024, import_usd: 3_000_000, yoy_growth: 0.05, cagr_3y: 0.04, screen_score: 70, is_transit_hub: true, is_mirror: false, tags: ["transit"], stage: 1 },
    { rank: 3, importer_iso3: "DEU", market_iso2: "DE", year: 2024, import_usd: 2_000_000, yoy_growth: 0.03, cagr_3y: 0.02, screen_score: 60, is_transit_hub: false, is_mirror: true, tags: ["mirror"], stage: 1 },
  ],
};

const BRIEF = {
  analysis_id: "an-1",
  hs_code: "080410",
  decision: "Prioritise India — the largest and fastest-growing market for HS 080410.",
  decisive_numbers: [
    { label: "Top market imports", value: "$5,000,000", source: "UN Comtrade 2024", year: 2024 },
  ],
  competitive_position: ["Saudi origin competes on quality and freight proximity."],
  limits: ["Mock data — not a live Comtrade pull."],
};

const DASHBOARD = {
  campaigns: 0,
  total_sent: 0,
  total_opened: 0,
  total_replied: 0,
  total_bounced: 0,
  open_rate: 0,
  reply_rate: 0,
  bounce_rate: 0,
  pending_approvals: 0,
};

test("full pipeline: login → upload → confirm HS → funnel → discover → campaign → approve", async ({
  page,
  context,
}) => {
  // Journey state that mocks read at call time.
  let hsConfirmed = false;
  let productsList: unknown[] = [];
  const posted: Record<string, unknown> = {};

  const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, json: body });

  // Fallback first; specific routes registered after it take precedence.
  await page.route(/\/api\/v1\//, (route) => json(route, []));

  await page.route(/\/api\/v1\/auth\/login$/, (route) =>
    json(route, { access_token: fakeToken() }),
  );
  await page.route(/\/api\/v1\/dashboard$/, (route) => json(route, DASHBOARD));

  await page.route(/\/api\/v1\/products$/, (route) => {
    if (route.request().method() === "POST") {
      productsList = [product(false)];
      return json(route, product(false), 201);
    }
    return json(route, productsList);
  });
  await page.route(/\/api\/v1\/products\/prod-1$/, (route) => json(route, product(hsConfirmed)));
  await page.route(/\/api\/v1\/products\/prod-1\/hs-code$/, (route) => {
    hsConfirmed = true;
    return json(route, product(true));
  });
  await page.route(/\/api\/v1\/products\/prod-1\/analysis$/, (route) => json(route, ANALYSIS, 201));
  await page.route(/\/api\/v1\/analyses\/an-1\/brief$/, (route) => json(route, BRIEF));
  await page.route(/\/api\/v1\/products\/prod-1\/discover$/, (route) => {
    posted.discover = route.request().postDataJSON();
    return json(route, { detail: "Discovery started", markets: ["IN", "NL", "DE"] }, 202);
  });
  await page.route(/\/api\/v1\/products\/prod-1\/buyers/, (route) => json(route, [BUYER_MATCH]));
  await page.route(/\/api\/v1\/sender-accounts$/, (route) => json(route, [VERIFIED_ACCOUNT]));

  await page.route(/\/api\/v1\/campaigns$/, (route) => {
    if (route.request().method() === "POST") {
      posted.campaign = route.request().postDataJSON();
      return json(route, { ...CAMPAIGN, id: "camp-1" }, 201);
    }
    return json(route, []);
  });
  await page.route(/\/api\/v1\/campaigns\/camp-1\/draft$/, (route) =>
    json(route, { detail: "Drafting started" }, 202),
  );
  await page.route(/\/api\/v1\/campaigns\/camp-1$/, (route) =>
    json(route, { ...CAMPAIGN, id: "camp-1", market_iso2: "IN" }),
  );
  await page.route(/\/api\/v1\/campaigns\/camp-1\/emails$/, (route) => json(route, EMAILS));
  await page.route(/\/api\/v1\/emails\/e1\/approve$/, (route) => {
    posted.approve = true;
    return json(route, { ...EMAILS[0], status: "approved" });
  });
  await page.route(/\/api\/v1\/emails\/e1\/queue$/, (route) =>
    json(route, { ...EMAILS[0], status: "queued" }),
  );

  // Approvals are guarded by a window.confirm — accept it.
  page.on("dialog", (d) => d.accept());

  // Pre-seed auth so every (app) page renders; the login step below still
  // exercises the sign-in button → POST → redirect.
  await context.addCookies([{ name: "silk_token", value: fakeToken(), url: BASE }]);

  // 1) Log in.
  await page.goto("/en/login");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);

  // 2) Upload a product.
  await page.goto("/en/products");
  await page.getByRole("button", { name: "Upload product" }).click();
  await page.getByLabel("Product name (Arabic)").fill("تمور فاخرة");
  await page.getByLabel("Product name (English)").fill("Premium Dates");
  const [productReq] = await Promise.all([
    page.waitForRequest((r) => r.url().endsWith("/api/v1/products") && r.method() === "POST"),
    page.getByRole("button", { name: "Create product" }).click(),
  ]);
  expect(productReq).toBeTruthy();
  await page.getByRole("link", { name: /Premium Dates/ }).click();
  await expect(page).toHaveURL(/\/products\/prod-1$/);

  // 3) Confirm the HS code, which unlocks "Find buyers".
  await page.getByRole("button", { name: /Dates, fresh or dried/ }).click();
  await page.getByRole("button", { name: "Confirm code" }).click();
  const findBuyers = page.getByRole("link", { name: "Find buyers" });
  await expect(findBuyers).toBeVisible();
  await findBuyers.click();
  await expect(page).toHaveURL(/\/products\/prod-1\/markets$/);

  // 4) Screen the world funnel, then discover across the top markets.
  await page.getByRole("button", { name: "Screen world markets" }).click();
  await expect(page.getByText(BRIEF.decision)).toBeVisible();
  await expect(page.getByText("IND", { exact: true })).toBeVisible(); // top-5 rendered
  await page.getByRole("button", { name: "Discover buyers across the top markets" }).click();
  await expect(page).toHaveURL(/\/products\/prod-1\/buyers$/);
  expect(posted.discover).toMatchObject({ markets: expect.arrayContaining(["IN"]) });

  // 5) Create the outreach campaign from the buyers view.
  await expect(page.getByText("Acme Importers")).toBeVisible();
  const [campaignReq] = await Promise.all([
    page.waitForRequest((r) => r.url().endsWith("/api/v1/campaigns") && r.method() === "POST"),
    page.getByRole("button", { name: "Create campaign" }).click(),
  ]);
  expect(campaignReq.postDataJSON()).toMatchObject({ product_id: "prod-1", market_iso2: "IN" });
  await expect(page).toHaveURL(/\/campaigns\/camp-1\/review$/);

  // 6) Approve a draft — the platform's core guarantee (I3), one explicit human action.
  const approve = page.getByRole("button", { name: "Approve" }).first();
  await expect(approve).toBeVisible();
  await Promise.all([
    page.waitForRequest((r) => r.url().endsWith("/api/v1/emails/e1/approve") && r.method() === "POST"),
    approve.click(),
  ]);
  expect(posted.approve).toBe(true);
});
