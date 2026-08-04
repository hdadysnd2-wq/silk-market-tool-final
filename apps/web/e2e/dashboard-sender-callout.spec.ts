import { test, expect, type Route } from "@playwright/test";
import { fakeToken, VERIFIED_ACCOUNT } from "./fixtures";

const BASE = "http://localhost:3100";
const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, json: body });

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

test("dashboard shows the connect-mailbox callout when no sender is verified", async ({
  page,
  context,
}) => {
  await context.addCookies([{ name: "silk_token", value: fakeToken(), url: BASE }]);
  await page.route(/\/api\/v1\//, (route) => json(route, []));
  await page.route(/\/api\/v1\/dashboard$/, (route) => json(route, DASHBOARD));
  await page.route(/\/api\/v1\/sender-accounts$/, (route) => json(route, []));

  await page.goto("/en/dashboard");

  await expect(page.getByText("Connect a sending mailbox")).toBeVisible();
  const cta = page.getByRole("link", { name: "Connect email" });
  await expect(cta).toBeVisible();
  await expect(cta).toHaveAttribute("href", /\/settings\/sending-email$/);
});

test("dashboard hides the callout once a mailbox is verified", async ({ page, context }) => {
  await context.addCookies([{ name: "silk_token", value: fakeToken(), url: BASE }]);
  await page.route(/\/api\/v1\//, (route) => json(route, []));
  await page.route(/\/api\/v1\/dashboard$/, (route) => json(route, DASHBOARD));
  await page.route(/\/api\/v1\/sender-accounts$/, (route) => json(route, [VERIFIED_ACCOUNT]));

  await page.goto("/en/dashboard");

  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await expect(page.getByText("Connect a sending mailbox")).toHaveCount(0);
});
