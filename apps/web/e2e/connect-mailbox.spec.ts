import { test, expect } from "@playwright/test";
import { fakeToken, VERIFIED_ACCOUNT } from "./fixtures";

const BASE = "http://localhost:3100";

/**
 * Connect-mailbox flow with mocked OAuth. The connect endpoint returns an
 * authorization_url pointing back at our own page with `?connected=1` (standing
 * in for the provider consent + callback round-trip); after it, the mailbox list
 * reports a verified account.
 */
test("connect a mailbox via the mocked OAuth flow", async ({ page, context }) => {
  await context.addCookies([{ name: "silk_token", value: fakeToken(), url: BASE }]);

  let connected = false;

  // Fallback registered first so the specific routes (registered later) win.
  await page.route(/\/api\/v1\//, (route) => route.fulfill({ json: [] }));

  await page.route(/\/api\/v1\/sender-accounts$/, (route) =>
    route.fulfill({ json: connected ? [VERIFIED_ACCOUNT] : [] }),
  );

  await page.route(/\/api\/v1\/sender-accounts\/connect\//, (route) => {
    connected = true;
    return route.fulfill({
      json: {
        authorization_url: `${BASE}/en/onboarding/email?connected=1&email=owner@factory.example`,
      },
    });
  });

  await page.goto("/en/onboarding/email");

  await expect(page.getByRole("heading", { name: "Connect your email" })).toBeVisible();
  await expect(page.getByText("No mailbox connected yet.")).toBeVisible();

  await page.getByRole("button", { name: "Connect Google" }).click();

  // The browser round-trips through the (mocked) provider back to ?connected=1.
  await expect(page.getByText(/is connected and verified/)).toBeVisible();
  await expect(page.getByText("owner@factory.example").first()).toBeVisible();
  await expect(page.getByText("Verified")).toBeVisible();
});
