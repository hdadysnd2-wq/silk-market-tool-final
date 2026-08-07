import { test, expect } from "@playwright/test";

// Wave 2: the CSP must carry a per-request script nonce instead of
// 'unsafe-inline'. 'unsafe-inline' in script-src neutralizes CSP against the
// injected-script attacks it exists for; the nonce policy only executes inline
// scripts the server stamped itself.

test("CSP uses a script nonce, not 'unsafe-inline', and the page still renders", async ({
  page,
}) => {
  const violations: string[] = [];
  page.on("console", (msg) => {
    if (msg.text().includes("Content Security Policy")) violations.push(msg.text());
  });

  const resp = await page.goto("/en/login");
  const csp = resp!.headers()["content-security-policy"] ?? "";
  const scriptSrc = csp.split(";").find((d) => d.trim().startsWith("script-src")) ?? "";

  expect(scriptSrc).toMatch(/'nonce-[A-Za-z0-9+/]+=*'/);
  expect(scriptSrc).not.toContain("'unsafe-inline'");

  // The page must actually work under the strict policy — Next's inline
  // bootstrap scripts have to carry the nonce, or hydration dies silently.
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
  expect(violations).toEqual([]);
});

test("the nonce differs per request", async ({ page }) => {
  const nonceOf = (csp: string) => /'nonce-([^']+)'/.exec(csp)?.[1];
  const first = nonceOf((await page.goto("/en/login"))!.headers()["content-security-policy"] ?? "");
  const second = nonceOf((await page.goto("/en/login"))!.headers()["content-security-policy"] ?? "");
  expect(first).toBeTruthy();
  expect(second).toBeTruthy();
  expect(first).not.toBe(second);
});
