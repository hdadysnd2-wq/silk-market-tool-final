import { test, expect, type BrowserContext, type Page, type Route } from "@playwright/test";
import { fakeToken, CAMPAIGN, EMAILS, BUYER_MATCH } from "./fixtures";

const BASE = "http://localhost:3100";

const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, json: body });

// A campaign review page wired up with two drafts (e1, e2), one approved (e3),
// and one sent (e4) — the mix that exercises both the draft action bar and the
// read-only path. The campaign is non-EU so no LIA gate stands in the way.
async function setup(page: Page, context: BrowserContext) {
  await context.addCookies([{ name: "silk_token", value: fakeToken(), url: BASE }]);
  // Fallback first; specific routes registered after it take precedence.
  await page.route(/\/api\/v1\//, (route) => json(route, []));
  await page.route(/\/api\/v1\/campaigns\/camp-1$/, (route) => json(route, CAMPAIGN));
  await page.route(/\/api\/v1\/campaigns\/camp-1\/emails$/, (route) => json(route, EMAILS));
  await page.route(/\/api\/v1\/products\/prod-1\/buyers/, (route) => json(route, [BUYER_MATCH]));
}

test("rejecting a draft posts the reject action — the negative of the I3 gate", async ({
  page,
  context,
}) => {
  await setup(page, context);
  let rejected = false;
  await page.route(/\/api\/v1\/emails\/e1\/reject$/, (route) => {
    rejected = true;
    return json(route, { ...EMAILS[0], status: "rejected" });
  });

  await page.goto("/en/campaigns/camp-1/review");

  await expect(page.getByText("Body e1")).toBeVisible();
  const reject = page.getByRole("button", { name: "Reject" }).first();
  await Promise.all([
    page.waitForRequest(
      (r) => r.url().endsWith("/api/v1/emails/e1/reject") && r.method() === "POST",
    ),
    reject.click(),
  ]);
  expect(rejected).toBe(true);
});

test("editing a draft saves the revised subject and body", async ({ page, context }) => {
  await setup(page, context);
  let saved: unknown = null;
  await page.route(/\/api\/v1\/emails\/e1$/, (route) => {
    if (route.request().method() === "PUT") {
      saved = route.request().postDataJSON();
      return json(route, { ...EMAILS[0], subject: "Edited subject", body_text: "Edited body copy" });
    }
    return json(route, EMAILS[0]);
  });

  await page.goto("/en/campaigns/camp-1/review");

  // Open the first draft's editor; only that card swaps into inputs.
  await page.getByRole("button", { name: "Edit" }).first().click();
  const subject = page.getByRole("textbox").first();
  const body = page.getByRole("textbox").nth(1);
  await expect(subject).toBeVisible();
  await subject.fill("Edited subject");
  await body.fill("Edited body copy");

  const [request] = await Promise.all([
    page.waitForRequest((r) => r.url().endsWith("/api/v1/emails/e1") && r.method() === "PUT"),
    page.getByRole("button", { name: "Save" }).click(),
  ]);
  expect(request.postDataJSON()).toMatchObject({
    subject: "Edited subject",
    body_text: "Edited body copy",
  });
  expect(saved).toMatchObject({ subject: "Edited subject", body_text: "Edited body copy" });
});

test("only draft emails expose the review action bar; approved and sent are read-only", async ({
  page,
  context,
}) => {
  await setup(page, context);

  await page.goto("/en/campaigns/camp-1/review");

  // All four emails render…
  await expect(page.getByText("Body e1")).toBeVisible();
  await expect(page.getByText("Body e4")).toBeVisible();

  // …but only the two drafts (e1, e2) get Edit / Reject / Approve controls. The
  // approved (e3) and sent (e4) cards are read-only.
  await expect(page.getByRole("button", { name: "Edit" })).toHaveCount(2);
  await expect(page.getByRole("button", { name: "Reject" })).toHaveCount(2);
  await expect(page.getByRole("button", { name: "Approve" })).toHaveCount(2);
});
