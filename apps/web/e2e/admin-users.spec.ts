import { test, expect, type Route } from "@playwright/test";
import { fakeToken } from "./fixtures";

const BASE = "http://localhost:3100";
const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, json: body });

const FACTORIES = [
  { id: "fac-1", name_en: "Dates Factory", name_ar: "مصنع التمور", sector: "Food" },
];

test("create an analyst, deactivate, then reactivate", async ({ page, context }) => {
  await context.addCookies([{ name: "silk_token", value: fakeToken("admin"), url: BASE }]);

  // Mutable server state the mocked routes read and write.
  const users: Record<string, unknown>[] = [];

  await page.route(/\/api\/v1\//, (route) => json(route, []));
  await page.route(/\/api\/v1\/admin\/factories$/, (route) => json(route, FACTORIES));
  await page.route(/\/api\/v1\/admin\/users$/, (route) => {
    if (route.request().method() === "POST") {
      const body = route.request().postDataJSON();
      const user = {
        id: `u-${users.length + 1}`,
        email: body.email,
        full_name: body.full_name,
        role: body.role,
        factory_id: body.factory_id,
        locale: "en",
        is_active: true,
        last_login_at: null,
        created_at: "2026-01-01T00:00:00Z",
      };
      users.push(user);
      return json(route, user, 201);
    }
    return json(route, users);
  });
  await page.route(/\/api\/v1\/admin\/users\/([^/]+)\/(activate|deactivate)$/, (route) => {
    const m = route.request().url().match(/users\/([^/]+)\/(activate|deactivate)$/)!;
    const u = users.find((x) => x.id === m[1])!;
    u.is_active = m[2] === "activate";
    return json(route, u);
  });

  await page.goto("/en/admin/users");
  await expect(page.getByRole("heading", { name: "Users" })).toBeVisible();

  // Create an analyst (no factory needed).
  await page.getByRole("button", { name: "Add user" }).click();
  await page.getByLabel("Email").fill("newanalyst@silk.co");
  await page.getByLabel("Role").selectOption("analyst");
  await page.getByRole("button", { name: "Create" }).click();

  const row = page.getByTestId("user-row").filter({ hasText: "newanalyst@silk.co" });
  await expect(row).toBeVisible();
  await expect(row.getByText("Active", { exact: true })).toBeVisible();

  // Deactivate.
  await row.getByRole("button", { name: "Deactivate" }).click();
  await expect(row.getByText("Inactive", { exact: true })).toBeVisible();

  // Reactivate.
  await row.getByRole("button", { name: "Activate" }).click();
  await expect(row.getByText("Active", { exact: true })).toBeVisible();
});

test("reset-password surfaces a confirmation without leaking a code", async ({ page, context }) => {
  await context.addCookies([{ name: "silk_token", value: fakeToken("admin"), url: BASE }]);
  const user = {
    id: "u-1",
    email: "someone@silk.co",
    full_name: null,
    role: "analyst",
    factory_id: null,
    locale: "en",
    is_active: true,
    last_login_at: null,
    created_at: "2026-01-01T00:00:00Z",
  };
  await page.route(/\/api\/v1\//, (route) => json(route, []));
  await page.route(/\/api\/v1\/admin\/factories$/, (route) => json(route, FACTORIES));
  await page.route(/\/api\/v1\/admin\/users$/, (route) => json(route, [user]));
  await page.route(/\/api\/v1\/admin\/users\/u-1\/reset-password$/, (route) =>
    route.fulfill({ status: 204 }),
  );

  await page.goto("/en/admin/users");
  const row = page.getByTestId("user-row").filter({ hasText: "someone@silk.co" });
  await row.getByRole("button", { name: "Reset password" }).click();
  await expect(page.getByRole("status")).toContainText("someone@silk.co");
});
