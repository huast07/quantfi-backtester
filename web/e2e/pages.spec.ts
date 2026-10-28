import { expect, expectNoHorizontalScroll, test } from "./fixtures";

test("every page loads, is not indexed and fits the screen", async ({ page }) => {
  for (const [path, heading] of [
    ["/", "Backtest your strategies"],
    ["/cases", "Case library"],
    ["/history", "History"],
    ["/results", "No run selected"],
  ]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { name: heading, level: 1 })).toBeVisible();
    await expect(page.locator('meta[name="robots"]')).toHaveAttribute("content", "noindex, nofollow");
    await expectNoHorizontalScroll(page);
  }
  await expect(page.getByRole("contentinfo")).toContainText("never leave your machine");
});

test("the case library filters cases and downloads a day", async ({ page }) => {
  await page.goto("/cases");
  await expect(page.locator("details")).toHaveCount(42);
  await page.getByLabel("Search cases").fill("crash");
  await expect(page.locator("details")).not.toHaveCount(42);

  await page.getByLabel("Search cases").fill("");
  const card = page.locator("details#basket-dislocation");
  await card.locator("summary").click();
  await expect(card.getByText("Gatev, Goetzmann & Rouwenhorst (2006)")).toBeVisible();
  const downloads: string[] = [];
  page.on("download", (download) => downloads.push(download.suggestedFilename()));
  await card.getByRole("button", { name: "Download day CSVs" }).click();
  await expect
    .poll(() => downloads.toSorted(), { timeout: 180_000 })
    .toEqual([
      "basket-dislocation_seed1_prices_round_1_day_1.csv",
      "basket-dislocation_seed1_trades_round_1_day_1.csv",
    ]);
});

test("a results link from another browser explains where runs live", async ({ page }) => {
  await page.goto("/results?id=not-in-this-browser");
  await expect(page.getByRole("heading", { name: "Run not found", level: 1 })).toBeVisible();
  await expect(page.getByText(/Results live in the browser that ran them/)).toBeVisible();
});
