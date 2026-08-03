import { test, expect, type BrowserContext, type Page } from "@playwright/test";
import type { SenderAccount } from "@/lib/types";
import { fakeToken, VERIFIED_ACCOUNT, BUYER_MATCH } from "./fixtures";

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
