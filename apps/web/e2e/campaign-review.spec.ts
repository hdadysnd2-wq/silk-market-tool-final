import { test, expect } from "@playwright/test";
import { fakeToken, CAMPAIGN, EMAILS, BUYER_MATCH } from "./fixtures";

const BASE = "http://localhost:3100";

test("the campaign review page is the approval gate: header + progress summary", async ({
  page,
  context,
}) => {
  await context.addCookies([{ name: "silk_token", value: fakeToken(), url: BASE }]);
  await page.route(/\/api\/v1\//, (route) => route.fulfill({ json: [] }));
  await page.route(/\/api\/v1\/campaigns\/camp-1\/emails$/, (route) =>
    route.fulfill({ json: EMAILS }),
  );
  await page.route(/\/api\/v1\/campaigns\/camp-1$/, (route) => route.fulfill({ json: CAMPAIGN }));
  await page.route(/\/api\/v1\/products\/[^/]+\/buyers/, (route) =>
    route.fulfill({ json: [BUYER_MATCH] }),
  );

  await page.goto("/en/campaigns/camp-1/review");

  // Campaign context header.
  await expect(page.getByRole("heading", { name: "Outreach → IN" })).toBeVisible();

  // The approval-gate summary: 2 pending review · 1 approved · 1 sent.
  const summary = page.getByRole("group", { name: "Approval progress" });
  await expect(summary).toBeVisible();
  await expect(summary.getByText("Pending review").locator("..")).toContainText("2");
  await expect(summary.getByText("Approved").locator("..")).toContainText("1");
  await expect(summary.getByText("Sent").locator("..")).toContainText("1");

  // The I3 guarantee is stated, and every draft is rendered for review.
  await expect(
    page.getByText("No email is ever sent without your explicit approval."),
  ).toBeVisible();
  await expect(page.getByText("Body e1")).toBeVisible();
});
