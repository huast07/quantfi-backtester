import path from "node:path";

import { test as base, expect, type Page } from "@playwright/test";

export const STRATEGIES = path.join(__dirname, "strategies");
export const strategy = (name: string) => path.join(STRATEGIES, name);

/** Fails any test whose page logged an error or threw, so regressions that only show in the console are caught. */
export const test = base.extend<{ consoleErrors: string[] }>({
  consoleErrors: [
    async ({ page }, use) => {
      const errors: string[] = [];
      page.on("console", (message) => {
        if (message.type() === "error") errors.push(message.text());
      });
      page.on("pageerror", (error) => errors.push(error.message));
      await use(errors);
      expect(errors, "console errors").toEqual([]);
    },
    { auto: true },
  ],
});

export { expect };

export async function uploadStrategies(page: Page, ...names: string[]) {
  await page.locator('input[type="file"][accept^=".py"]').setInputFiles(names.map(strategy));
}

/** Uploads the files, waits for every check to pass, picks the Quick suite and starts the run. */
export async function startQuickRun(page: Page, ...names: string[]) {
  await page.goto("/");
  await uploadStrategies(page, ...names);
  await expect(page.getByText("Ready", { exact: true })).toHaveCount(names.length, { timeout: 180_000 });
  await page.getByRole("radio", { name: /Quick/ }).check({ force: true });
  await page.getByRole("button", { name: "Run backtest" }).click();
}

export async function expectNoHorizontalScroll(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow, "horizontal overflow in px").toBeLessThanOrEqual(0);
}
