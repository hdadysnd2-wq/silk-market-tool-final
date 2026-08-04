import { test, expect, type Page, type Route } from "@playwright/test";
import { fakeToken } from "./fixtures";

const BASE = "http://localhost:3100";
const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, json: body });

// Open the products page and the upload dialog with required names filled.
// `onPost` handles POST /products; GET /products always returns an empty list.
async function openDialog(page: Page, onPost: (route: Route) => unknown) {
  await page.route(/\/api\/v1\//, (route) => json(route, []));
  await page.route(/\/api\/v1\/products$/, (route) =>
    route.request().method() === "POST" ? onPost(route) : json(route, []),
  );
  await page.goto("/en/products");
  await page.getByRole("button", { name: "Upload product" }).click();
  await page.getByLabel("Product name (Arabic)").fill("منتج");
  await page.getByLabel("Product name (English)").fill("Widget");
}

test("a failed create shows an inline error and keeps the dialog open", async ({
  page,
  context,
}) => {
  await context.addCookies([{ name: "silk_token", value: fakeToken(), url: BASE }]);
  await openDialog(page, (route) =>
    json(route, { detail: "price_min must be a number or left blank" }, 400),
  );

  await page.getByRole("button", { name: "Create product" }).click();

  // The server detail is surfaced inline… (scope past Next's empty route-announcer alert)
  await expect(page.getByText("Couldn't add the product:")).toBeVisible();
  await expect(page.getByText(/price_min must be a number/)).toBeVisible();
  // …and the dialog stays open so the operator can fix and retry.
  await expect(page.getByRole("button", { name: "Create product" })).toBeVisible();
});

test("a successful create closes the dialog and shows a success notice", async ({
  page,
  context,
}) => {
  await context.addCookies([{ name: "silk_token", value: fakeToken(), url: BASE }]);
  await openDialog(page, (route) =>
    json(route, { task_id: "t1", product: { id: "p1", classification_status: "pending" } }, 202),
  );

  await page.getByRole("button", { name: "Create product" }).click();

  // Dialog closes (its submit button is gone) and a success notice appears.
  await expect(page.getByRole("button", { name: "Create product" })).toHaveCount(0);
  await expect(page.getByRole("status")).toContainText("Product added");
});

test("min price above max is rejected client-side without a request", async ({ page, context }) => {
  await context.addCookies([{ name: "silk_token", value: fakeToken(), url: BASE }]);
  let posted = false;
  await openDialog(page, (route) => {
    posted = true;
    return json(route, {}, 202);
  });

  await page.getByLabel("Min price").fill("20");
  await page.getByLabel("Max price").fill("10");
  await page.getByRole("button", { name: "Create product" }).click();

  await expect(page.getByText(/minimum price can't be greater/)).toBeVisible();
  expect(posted).toBe(false);
});
