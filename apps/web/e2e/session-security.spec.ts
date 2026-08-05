import { test, expect, type Route } from "@playwright/test";
import { fakeToken } from "./fixtures";

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

test("login goes through the session route handler and reaches the dashboard", async ({
  page,
}) => {
  await page.route(/\/api\/v1\//, (route) => json(route, []));
  await page.route(/\/api\/v1\/dashboard$/, (route) => json(route, DASHBOARD));
  // The session route handler sets the httpOnly cookie server-side; mock it to
  // return the role and set a valid signed cookie.
  await page.route(/\/api\/session\/login$/, (route) =>
    route.fulfill({
      status: 200,
      headers: {
        "content-type": "application/json",
        "set-cookie": `silk_token=${fakeToken("factory_user")}; Path=/; HttpOnly; SameSite=Lax`,
      },
      body: JSON.stringify({ role: "factory_user" }),
    }),
  );

  await page.goto("/en/login");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/dashboard/);
});

test("the session token is not exposed to client JS (httpOnly)", async ({ page, context }) => {
  await context.addCookies([
    { name: "silk_token", value: fakeToken("factory_user"), url: BASE, httpOnly: true },
  ]);
  await page.route(/\/api\/v1\//, (route) => json(route, []));
  await page.route(/\/api\/v1\/dashboard$/, (route) => json(route, DASHBOARD));

  await page.goto("/en/dashboard");
  const cookies = await page.evaluate(() => document.cookie);
  expect(cookies).not.toContain("silk_token");
});

test("security headers are present on a page response", async ({ page }) => {
  const resp = await page.goto("/en/login");
  const headers = resp!.headers();
  expect(headers["content-security-policy"]).toBeTruthy();
  expect(headers["x-content-type-options"]).toBe("nosniff");
  expect(headers["x-frame-options"]).toBe("DENY");
  expect(headers["content-security-policy"]).toContain("frame-ancestors 'none'");
});

test("logout clears the session cookie via the route handler", async ({ page }) => {
  const resp = await page.request.post(`${BASE}/api/session/logout`);
  expect(resp.status()).toBe(200);
  const setCookie = resp.headers()["set-cookie"] ?? "";
  expect(setCookie).toContain("silk_token=");
  expect(setCookie.toLowerCase()).toContain("httponly");
});
