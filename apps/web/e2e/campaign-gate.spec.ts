import { test, expect, type BrowserContext, type Page } from "@playwright/test";
import type { SenderAccount } from "@/lib/types";
import { fakeToken, VERIFIED_ACCOUNT, BUYER_MATCH, BUYER_MATCH_NL } from "./fixtures";

const BASE = "http://localhost:3100";

async function setup(page: Page, context: BrowserContext, senders: SenderAccount[]) {
  await context.addCookies([{ name: "silk_token", value: fakeToken(), url: BASE }]);
  // Fallback first; specific routes registered after it take precedence.
  await page.route(/\/api\/v1\//, (route) => route.fulfill({ json: [] }));
  await page.route(/\/api\/v1\/products\/[^/]+\/buyers/, (route) =>
    route.fulfill({ json: [BUYER_MATCH] }),
  );
  await page.route(/\/api\/v1\/sender-accounts$/, (route) => route.fulfill({ json: senders }));
}

test("campaign creation is blocked without a verified sender mailbox", async ({
  page,
  context,
}) => {
  await setup(page, context, []); // no connected mailbox

  await page.goto("/en/products/prod-1/buyers?market=IN");

  await expect(page.getByRole("link", { name: "Connect email to send" })).toBeVisible();
  await expect(
    page.getByText("Connect and verify a sender mailbox before creating campaigns."),
  ).toBeVisible();
  // The create button is not offered at all.
  await expect(page.getByRole("button", { name: "Create campaign" })).toHaveCount(0);
});

test("campaign creation is offered once a verified sender exists", async ({ page, context }) => {
  await setup(page, context, [VERIFIED_ACCOUNT]);

  await page.goto("/en/products/prod-1/buyers?market=IN");

  await expect(page.getByRole("button", { name: "Create campaign" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Connect email to send" })).toHaveCount(0);
});

test("the unfiltered multi-market buyers view lets you pick the outreach market", async ({
  page,
  context,
}) => {
  await context.addCookies([{ name: "silk_token", value: fakeToken(), url: BASE }]);
  await page.route(/\/api\/v1\//, (route) => route.fulfill({ json: [] }));
  // Two buyers in different markets — the "discover across the top markets" landing.
  await page.route(/\/api\/v1\/products\/[^/]+\/buyers/, (route) =>
    route.fulfill({ json: [BUYER_MATCH, BUYER_MATCH_NL] }),
  );
  await page.route(/\/api\/v1\/sender-accounts$/, (route) =>
    route.fulfill({ json: [VERIFIED_ACCOUNT] }),
  );
  // Capture the created campaign so we can assert it targets the chosen market.
  await page.route(/\/api\/v1\/campaigns$/, (route) => {
    if (route.request().method() === "POST") {
      return route.fulfill({ json: { id: "camp-1" } });
    }
    return route.fulfill({ json: [] });
  });
  await page.route(/\/api\/v1\/campaigns\/camp-1\/draft$/, (route) =>
    route.fulfill({ status: 202, json: { detail: "Drafting started" } }),
  );

  // No ?market= filter: the list spans IN and NL.
  await page.goto("/en/products/prod-1/buyers");

  const picker = page.getByLabel("Outreach market");
  await expect(picker).toBeVisible();
  const createBtn = page.getByRole("button", { name: "Create campaign" });
  await expect(createBtn).toBeEnabled();

  // Choosing NL must drive the campaign's market — not the default first option.
  await picker.selectOption("NL");
  const [request] = await Promise.all([
    page.waitForRequest(
      (r) => r.url().endsWith("/api/v1/campaigns") && r.method() === "POST",
    ),
    createBtn.click(),
  ]);
  expect(request.postDataJSON()).toMatchObject({ product_id: "prod-1", market_iso2: "NL" });

  // Drafting kicks off and the user is taken into the review flow.
  await expect(page).toHaveURL(/\/campaigns\/camp-1\/review$/);
});
