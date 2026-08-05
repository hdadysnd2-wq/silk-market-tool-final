import { test, expect, type Route } from "@playwright/test";
import { fakeToken, FACTORY } from "./fixtures";

const BASE = "http://localhost:3100";

const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, json: body });

test("running the DNS check posts to the check endpoint and reflects the result", async ({
  page,
  context,
}) => {
  await context.addCookies([{ name: "silk_token", value: fakeToken(), url: BASE }]);
  await page.route(/\/api\/v1\//, (route) => json(route, []));

  // The server verifies SPF/DKIM/DMARC; the tenant cannot self-attest them. Once
  // the check runs, the factory GET reflects the resolved (verified) state.
  let checked = false;
  await page.route(/\/api\/v1\/factory$/, (route) => json(route, { ...FACTORY, spf_ok: checked }));
  let posted = false;
  await page.route(/\/api\/v1\/factory\/deliverability\/check$/, (route) => {
    posted = true;
    checked = true;
    return json(route, {
      spf_ok: true,
      dkim_ok: false,
      dmarc_ok: false,
      notes: { spf: "SPF record found" },
    });
  });

  await page.goto("/en/settings/deliverability");

  // Status is read-only now — no toggle button inside the row.
  const spfRow = page.getByRole("listitem").filter({ hasText: "SPF record" });
  // Exact match: "Verified" is a substring of "Not verified".
  await expect(spfRow.getByText("Not verified", { exact: true })).toBeVisible();
  await expect(spfRow.getByRole("button")).toHaveCount(0);

  await Promise.all([
    page.waitForRequest(
      (r) =>
        r.url().endsWith("/api/v1/factory/deliverability/check") && r.method() === "POST",
    ),
    page.getByRole("button", { name: "Run check" }).click(),
  ]);
  expect(posted).toBe(true);
  // After the check + reload, SPF now reads as verified.
  await expect(spfRow.getByText("Verified", { exact: true })).toBeVisible();
});

test("starting warm-up posts start_warmup and then hides the button", async ({ page, context }) => {
  await context.addCookies([{ name: "silk_token", value: fakeToken(), url: BASE }]);
  await page.route(/\/api\/v1\//, (route) => json(route, []));

  // The factory's warm-up day advances to 1 once warm-up has started.
  let started = false;
  await page.route(/\/api\/v1\/factory$/, (route) =>
    json(route, { ...FACTORY, warmup_day: started ? 1 : 0 }),
  );
  let payload: unknown = null;
  await page.route(/\/api\/v1\/factory\/deliverability$/, (route) => {
    payload = route.request().postDataJSON();
    started = true;
    return json(route, { ...FACTORY, warmup_day: 1 });
  });

  await page.goto("/en/settings/deliverability");

  const startWarmup = page.getByRole("button", { name: "Start warm-up" });
  await expect(startWarmup).toBeVisible();
  await Promise.all([
    page.waitForRequest(
      (r) => r.url().endsWith("/api/v1/factory/deliverability") && r.method() === "PUT",
    ),
    startWarmup.click(),
  ]);
  expect(payload).toMatchObject({ start_warmup: true });

  // Once warm-up is under way (day 1) the start button is no longer offered.
  await expect(page.getByRole("button", { name: "Start warm-up" })).toHaveCount(0);
});

test("the admin console switches between factories, suppression and audit tabs", async ({
  page,
  context,
}) => {
  await context.addCookies([{ name: "silk_token", value: fakeToken(), url: BASE }]);
  await page.route(/\/api\/v1\//, (route) => json(route, []));
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

  // Factories is the default tab.
  await expect(page.getByText("Dates Factory")).toBeVisible();

  // Suppression tab lists blocked recipients.
  await page.getByRole("button", { name: "suppression" }).click();
  await expect(page.getByText("blocked@buyer.example")).toBeVisible();

  // Audit tab lists the action log.
  await page.getByRole("button", { name: "audit" }).click();
  await expect(page.getByText("email.approved")).toBeVisible();
});
