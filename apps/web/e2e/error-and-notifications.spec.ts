import { test, expect, type Route } from "@playwright/test";
import { fakeToken } from "./fixtures";

const BASE = "http://localhost:3100";
const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, json: body });

// Audit 2026-08-07: a failed load must render a real error state, not the
// "you have no data" empty state; operator notifications must be visible.

test("a 500 on the campaigns list shows an error state, not an empty state", async ({
  page,
  context,
}) => {
  await context.addCookies([{ name: "silk_token", value: fakeToken(), url: BASE }]);
  await page.route(/\/api\/v1\//, (route) => json(route, []));
  await page.route(/\/api\/v1\/campaigns$/, (route) =>
    route.fulfill({ status: 500, json: { detail: "boom" } }),
  );

  await page.goto("/en/campaigns");

  // Scope to the error alert by its text — the page also carries Next.js's
  // empty route-announcer with role="alert", so a bare getByRole is ambiguous.
  const alert = page.getByRole("alert").filter({ hasText: "Something went wrong" });
  await expect(alert).toBeVisible();
  await expect(alert.getByRole("button", { name: "Try again" })).toBeVisible();
  // The empty-state copy must NOT be shown when the request failed.
  await expect(page.getByText("No campaigns yet")).toHaveCount(0);
});

test("the notifications bell shows an unread count and marks read", async ({ page, context }) => {
  await context.addCookies([{ name: "silk_token", value: fakeToken(), url: BASE }]);
  const notifications = [
    {
      id: "n1",
      kind: "mailbox_needs_reauth",
      title: "Reconnect your mailbox",
      body: "Sending from x@y is paused.",
      read_at: null,
      created_at: "2026-08-07T09:00:00Z",
    },
  ];
  await page.route(/\/api\/v1\//, (route) => json(route, []));
  await page.route(/\/api\/v1\/dashboard$/, (route) =>
    json(route, {
      campaigns: 0,
      total_sent: 0,
      total_replied: 0,
      total_bounced: 0,
      reply_rate: 0,
      bounce_rate: 0,
      pending_approvals: 0,
    }),
  );
  await page.route(/\/api\/v1\/notifications$/, (route) => json(route, notifications));
  await page.route(/\/api\/v1\/notifications\/n1\/read$/, (route) => {
    notifications[0].read_at = "2026-08-07T09:05:00Z";
    return json(route, notifications[0]);
  });

  await page.goto("/en/dashboard");

  // Unread badge shows "1" — scoped to the bell so it can't match a stray "1".
  const bell = page.getByRole("button", { name: "Notifications" });
  await expect(bell).toBeVisible();
  await expect(bell.getByText("1", { exact: true })).toBeVisible();

  await bell.click();
  await expect(page.getByText("Reconnect your mailbox")).toBeVisible();
  await page.getByRole("button", { name: "Mark read" }).click();
  // After marking read the unread badge is gone.
  await expect(bell.getByText("1", { exact: true })).toHaveCount(0);
});
