import { test, expect, type Route } from "@playwright/test";
import { fakeToken } from "./fixtures";

const BASE = "http://localhost:3100";
const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, json: body });

// Symptom B regression (Wave 3): an analysis that fails server-side in under a
// second used to spin for the full 3-minute poll window and then surface the
// raw "pollUntil: timed out after 180000ms". The funnel must stop polling on
// status="failed" and show the persisted failure_reason immediately.

const FAILED_REASON =
  "No world-trade data for HS 392010. A coverage sync has been requested — please retry in a few minutes.";

const product = {
  id: "prod-1",
  factory_id: "fac-1",
  name_ar: "فيلم",
  name_en: "Stretch Film",
  description_ar: null,
  description_en: null,
  image_url: null,
  price_min: null,
  price_max: null,
  currency: "USD",
  hs_code: "392010",
  hs_confirmed_by_user: true,
  hs_candidates: [],
  classification_status: "classified",
  failure_reason: null,
  created_at: "2026-01-01T00:00:00Z",
};

test("a failed analysis surfaces its persisted reason immediately, not a poll timeout", async ({
  page,
  context,
}) => {
  await context.addCookies([{ name: "silk_token", value: fakeToken(), url: BASE }]);
  await page.route(/\/api\/v1\//, (route) => json(route, []));
  await page.route(/\/api\/v1\/products\/prod-1$/, (route) => json(route, product));
  await page.route(/\/api\/v1\/products\/prod-1\/analysis$/, (route) =>
    json(
      route,
      { task_id: "t-1", analysis: { id: "an-1", status: "pending", rankings: [] } },
      202,
    ),
  );
  await page.route(/\/api\/v1\/analyses\/an-1$/, (route) =>
    json(route, {
      id: "an-1",
      product_id: "prod-1",
      product_name: "Stretch Film",
      status: "failed",
      failure_reason: FAILED_REASON,
      deepen: false,
      created_at: "2026-01-01T00:00:00Z",
      total_screened: null,
      rankings: [],
    }),
  );

  await page.goto("/en/products/prod-1/markets");
  const started = Date.now();
  await page.getByRole("button", { name: "Screen world markets" }).click();

  // The persisted reason — not a generic timeout — and fast.
  await expect(page.getByText(/No world-trade data for HS 392010/)).toBeVisible({
    timeout: 15_000,
  });
  expect(Date.now() - started).toBeLessThan(30_000);
  await expect(page.getByText(/pollUntil/)).toHaveCount(0);
});
