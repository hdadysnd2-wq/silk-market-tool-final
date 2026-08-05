import { test, expect, type Route } from "@playwright/test";
import { fakeToken } from "./fixtures";

const BASE = "http://localhost:3100";
const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, json: body });

const OVERVIEW = {
  factories: 6,
  active_campaigns: 3,
  pending_approvals: 4,
  total_sent: 200,
  bounce_rate: 0.025,
  complaint_rate: 0.01,
};

async function staffCookie(context: import("@playwright/test").BrowserContext) {
  await context.addCookies([{ name: "silk_token", value: fakeToken("admin"), url: BASE }]);
}

test("staff land on the admin overview with cross-tenant data", async ({ page, context }) => {
  await staffCookie(context);
  await page.route(/\/api\/v1\//, (route) => json(route, []));
  await page.route(/\/api\/v1\/admin\/overview$/, (route) => json(route, OVERVIEW));

  await page.goto("/en/admin");

  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  // B1 aggregates render as tiles ("Active campaigns" is unique to the overview;
  // the nav item is just "Campaigns").
  await expect(page.getByText("Active campaigns")).toBeVisible();
  await expect(page.getByText("2.5%")).toBeVisible(); // bounce rate
  await expect(page.getByText("1%")).toBeVisible(); // complaint rate
});

test("a factory user is redirected away from the admin console", async ({ page, context }) => {
  await context.addCookies([{ name: "silk_token", value: fakeToken("factory_user"), url: BASE }]);
  await page.route(/\/api\/v1\//, (route) => json(route, []));
  await page.route(/\/api\/v1\/dashboard$/, (route) =>
    json(route, {
      campaigns: 0,
      total_sent: 0,
      total_opened: 0,
      total_replied: 0,
      total_bounced: 0,
      open_rate: 0,
      reply_rate: 0,
      bounce_rate: 0,
      pending_approvals: 0,
    }),
  );

  await page.goto("/en/admin");

  // The (admin) layout bounces non-staff to their own dashboard.
  await expect(page).toHaveURL(/\/en\/dashboard/);
});

test("the admin nav routes to factories, suppression and audit pages", async ({ page, context }) => {
  await staffCookie(context);
  await page.route(/\/api\/v1\//, (route) => json(route, []));
  await page.route(/\/api\/v1\/admin\/overview$/, (route) => json(route, OVERVIEW));
  await page.route(/\/api\/v1\/admin\/factories$/, (route) =>
    json(route, [
      {
        id: "fac-1",
        name_en: "Dates Factory",
        sector: "Food & Agriculture",
        sending_domain: "mail.factory.example",
        spf_ok: true,
        dkim_ok: true,
        dmarc_ok: true,
      },
    ]),
  );
  await page.route(/\/api\/v1\/admin\/suppression$/, (route) =>
    json(route, [
      { email: "blocked@buyer.example", reason: "hard_bounce", created_at: "2026-01-01T00:00:00Z" },
    ]),
  );
  await page.route(/\/api\/v1\/admin\/audit$/, (route) =>
    json(route, [
      {
        id: 1,
        action: "email.approved",
        entity_type: "email",
        entity_id: "e1",
        actor_label: "owner@factory.example",
        occurred_at: "2026-01-01T00:00:00Z",
      },
    ]),
  );

  await page.goto("/en/admin");

  await page.getByRole("link", { name: "Factories" }).click();
  await expect(page.getByText("Dates Factory")).toBeVisible();

  await page.getByRole("link", { name: "Suppression" }).click();
  await expect(page.getByText("blocked@buyer.example")).toBeVisible();

  await page.getByRole("link", { name: "Audit" }).click();
  await expect(page.getByText("email.approved")).toBeVisible();
});
