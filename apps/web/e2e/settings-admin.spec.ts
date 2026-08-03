import { test, expect, type Route } from "@playwright/test";
import { fakeToken, FACTORY } from "./fixtures";

const BASE = "http://localhost:3100";

const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, json: body });

test("verifying a DNS record posts the toggle to the deliverability endpoint", async ({
  page,
  context,
}) => {
  await context.addCookies([{ name: "silk_token", value: fakeToken(), url: BASE }]);
  await page.route(/\/api\/v1\//, (route) => json(route, []));
  await page.route(/\/api\/v1\/factory$/, (route) => json(route, FACTORY));

  let payload: unknown = null;
  await page.route(/\/api\/v1\/factory\/deliverability$/, (route) => {
    payload = route.request().postDataJSON();
    return json(route, { ...FACTORY, spf_ok: true });
  });

  await page.goto("/en/settings/deliverability");

  // SPF starts unverified; its row button flips it on.
  const spfRow = page.getByRole("listitem").filter({ hasText: "SPF record" });
  const toggle = spfRow.getByRole("button");
  await expect(toggle).toHaveText("Not verified");
  const [request] = await Promise.all([
    page.waitForRequest(
      (r) => r.url().endsWith("/api/v1/factory/deliverability") && r.method() === "PUT",
    ),
    toggle.click(),
  ]);
  expect(request.postDataJSON()).toMatchObject({ spf_ok: true });
  expect(payload).toMatchObject({ spf_ok: true });
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
