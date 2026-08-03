import { test, expect } from "@playwright/test";
import { fakeToken, CAMPAIGN, EMAILS, BUYER_MATCH } from "./fixtures";

const BASE = "http://localhost:3100";

test("an EU-market campaign gates the approval screen on a Legitimate Interest Assessment", async ({
  page,
  context,
}) => {
  await context.addCookies([{ name: "silk_token", value: fakeToken(), url: BASE }]);
  await page.route(/\/api\/v1\//, (route) => route.fulfill({ json: [] }));
  await page.route(/\/api\/v1\/campaigns\/camp-eu\/emails$/, (route) =>
    route.fulfill({ json: EMAILS }),
  );
  await page.route(/\/api\/v1\/products\/[^/]+\/buyers/, (route) =>
    route.fulfill({ json: [BUYER_MATCH] }),
  );

  // The campaign is stateful: no LIA on file until the POST lands, then recorded.
  let liaRecorded = false;
  await page.route(/\/api\/v1\/campaigns\/camp-eu\/lia$/, (route) => {
    liaRecorded = true;
    return route.fulfill({ status: 201, json: { detail: "LIA recorded" } });
  });
  await page.route(/\/api\/v1\/campaigns\/camp-eu$/, (route) =>
    route.fulfill({
      json: {
        ...CAMPAIGN,
        id: "camp-eu",
        market_iso2: "DE",
        market_is_eu: true,
        lia_recorded: liaRecorded,
      },
    }),
  );

  await page.goto("/en/campaigns/camp-eu/review");

  // The gate is shown and blocks until the required fields are filled.
  const submit = page.getByRole("button", { name: "Record assessment" });
  await expect(submit).toBeVisible();
  await expect(submit).toBeDisabled();

  await page.getByLabel("Purpose of processing").fill("Offer Saudi dates to an EU importer.");
  await page.getByLabel("Why direct contact is necessary").fill("Only way to open a B2B trade talk.");
  await page.getByLabel("Balancing test").fill("Business contact, relevant offer, easy opt-out.");
  await expect(submit).toBeEnabled();

  // Recording posts the assessment…
  const [request] = await Promise.all([
    page.waitForRequest(
      (r) => r.url().endsWith("/api/v1/campaigns/camp-eu/lia") && r.method() === "POST",
    ),
    submit.click(),
  ]);
  expect(request.postDataJSON()).toMatchObject({
    purpose_text: "Offer Saudi dates to an EU importer.",
    necessity_text: "Only way to open a B2B trade talk.",
    balancing_test_text: "Business contact, relevant offer, easy opt-out.",
  });

  // …and the refetched campaign now reports the LIA, so the gate clears.
  await expect(page.getByRole("button", { name: "Record assessment" })).toHaveCount(0);
});
