import { existsSync } from "node:fs";
import { defineConfig, devices } from "@playwright/test";

const PORT = 3100;
const BASE_URL = `http://localhost:${PORT}`;

// Use the environment-provided Chromium when present (its version may not match
// the pinned @playwright/test, so we point straight at the binary); otherwise
// fall back to Playwright's own managed browser (`npx playwright install`).
const CHROMIUM = "/opt/pw-browsers/chromium";
const launchOptions = existsSync(CHROMIUM) ? { executablePath: CHROMIUM } : {};

export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: "line",
  use: {
    baseURL: BASE_URL,
    navigationTimeout: 90_000,
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], launchOptions },
    },
  ],
  webServer: {
    command: "pnpm dev",
    url: BASE_URL,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    // The API is mocked at the network layer in every test, so the backend proxy
    // target is never actually reached.
    env: { PORT: String(PORT), API_PROXY_TARGET: "http://127.0.0.1:9" },
  },
});
