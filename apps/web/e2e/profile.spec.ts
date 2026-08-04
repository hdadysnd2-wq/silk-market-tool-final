import { test, expect, type Route } from "@playwright/test";
import { fakeToken, FACTORY } from "./fixtures";

const BASE = "http://localhost:3100";
const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, json: body });

const ME = {
  id: "u1",
  email: "owner@factory.example",
  full_name: "Owner",
  role: "factory_user",
  factory_id: "fac-1",
  locale: "en",
};

test("edit factory name and change password round-trip", async ({ page, context }) => {
  await context.addCookies([{ name: "silk_token", value: fakeToken(), url: BASE }]);
  await page.route(/\/api\/v1\//, (route) => json(route, []));
  await page.route(/\/api\/v1\/factory$/, (route) => json(route, FACTORY));
  await page.route(/\/api\/v1\/auth\/me$/, (route) => json(route, ME));

  let factoryPayload: Record<string, unknown> | null = null;
  await page.route(/\/api\/v1\/factory$/, (route) => {
    if (route.request().method() === "PUT") {
      factoryPayload = route.request().postDataJSON();
      return json(route, { ...FACTORY, ...(factoryPayload ?? {}) });
    }
    return json(route, FACTORY);
  });

  let passwordPayload: Record<string, unknown> | null = null;
  await page.route(/\/api\/v1\/auth\/change-password$/, (route) => {
    passwordPayload = route.request().postDataJSON();
    return route.fulfill({ status: 204, body: "" });
  });

  await page.goto("/en/settings/profile");

  // Factory section: edit the English name and save → PUT /factory.
  const nameEn = page.getByLabel("Factory name (English)");
  await expect(nameEn).toHaveValue("Dates Factory");
  await nameEn.fill("Dates Factory Co");
  const [factoryReq] = await Promise.all([
    page.waitForRequest(
      (r) => r.url().endsWith("/api/v1/factory") && r.method() === "PUT",
    ),
    page.getByRole("button", { name: "Save factory" }).click(),
  ]);
  expect(factoryReq.postDataJSON()).toMatchObject({ name_en: "Dates Factory Co" });
  await expect(page.getByText("Saved.").first()).toBeVisible();

  // Sending domain + DNS chips are shown read-only.
  await expect(page.getByText("mail.factory.example")).toBeVisible();

  // Password section: change password → POST /auth/change-password (204).
  await page.getByLabel("Current password").fill("Passw0rd!");
  await page.getByLabel("New password", { exact: true }).fill("BrandNew1!");
  await page.getByLabel("Confirm new password").fill("BrandNew1!");
  await Promise.all([
    page.waitForRequest(
      (r) => r.url().endsWith("/api/v1/auth/change-password") && r.method() === "POST",
    ),
    page.getByRole("button", { name: "Change password" }).click(),
  ]);
  expect(passwordPayload).toMatchObject({
    current_password: "Passw0rd!",
    new_password: "BrandNew1!",
  });
  await expect(page.getByText("Password changed.")).toBeVisible();
});

test("profile page renders RTL in Arabic", async ({ page, context }) => {
  await context.addCookies([{ name: "silk_token", value: fakeToken(), url: BASE }]);
  await page.route(/\/api\/v1\//, (route) => json(route, []));
  await page.route(/\/api\/v1\/factory$/, (route) => json(route, FACTORY));
  await page.route(/\/api\/v1\/auth\/me$/, (route) => json(route, { ...ME, locale: "ar" }));

  await page.goto("/ar/settings/profile");
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(page.getByRole("heading", { name: "الملف الشخصي والحساب" })).toBeVisible();
});
