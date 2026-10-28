import { defineConfig, devices } from "@playwright/test";

// Point E2E_BASE_URL at a deployment (for example the Vercel production URL) to test it; without it the suite serves
// the local static export, so run `npm run build` first.
const baseURL = process.env.E2E_BASE_URL ?? "http://localhost:3400";

export default defineConfig({
  testDir: "e2e",
  // A run boots Pyodide (about 40 MB) and simulates real days, so tests take tens of seconds.
  timeout: 5 * 60_000,
  expect: { timeout: 20_000 },
  fullyParallel: true,
  workers: 2,
  retries: 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: { baseURL, trace: "retain-on-failure", screenshot: "only-on-failure" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 900 } } },
    { name: "phone", use: { ...devices["Pixel 7"] } },
  ],
  webServer: process.env.E2E_BASE_URL
    ? undefined
    : { command: "npx serve@14.2.6 out -l 3400", url: baseURL, reuseExistingServer: true },
});
