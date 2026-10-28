import { expect, expectNoHorizontalScroll, startQuickRun, test, uploadStrategies } from "./fixtures";

const RUN_TIMEOUT = 4 * 60_000;

test("compares two strategies on the quick suite and replays a case", async ({ page }) => {
  await startQuickRun(page, "amethyst_mm.py", "fades.py");
  await expect(page.getByRole("progressbar", { name: "Days simulated" })).toBeVisible();

  await page.waitForURL(/\/results\?id=/, { timeout: RUN_TIMEOUT });
  await expect(page.getByRole("heading", { name: "Results", level: 1 })).toBeVisible();
  await expect(page.getByText(/This suite is small/)).toBeVisible();
  await expect(page.getByRole("article")).toHaveCount(2);
  await expect(page.getByRole("heading", { name: "Head to head", level: 2 })).toBeVisible();
  await expect(page.getByRole("button", { name: /^fades\.py on TELLURIUM storm: -[\d,]+, weak$/ })).toBeVisible();

  // Replay one upload on one case: charts render and the trace matches the cell.
  await page.getByRole("button", { name: /^amethyst_mm\.py on Busy day/ }).click();
  const replay = page.locator("section").filter({ has: page.getByRole("heading", { name: "Replay", level: 2 }) });
  await expect(replay.getByRole("heading", { level: 3 })).toHaveText("amethyst_mm.py on Busy day");
  await expect(replay.locator("canvas")).toHaveCount(3, { timeout: 120_000 });
  await expect(replay.getByText("AMETHYST mid price and fills")).toBeVisible();

  const download = page.waitForEvent("download");
  await replay.getByRole("button", { name: "Save PNG" }).first().click();
  expect((await download).suggestedFilename()).toBe("amethyst_mm-busy-day-seed1-AMETHYST-price.png");

  await expectNoHorizontalScroll(page);

  // The run is in History and reopens from there.
  await page.getByRole("link", { name: "History" }).first().click();
  await page.getByRole("link", { name: "amethyst_mm.py vs fades.py" }).click();
  await expect(page.getByRole("heading", { name: "Strategy by case", level: 2 })).toBeVisible();
});

test("explains files that cannot run", async ({ page }) => {
  await page.goto("/");
  await uploadStrategies(page, "broken.py");
  await expect(page.getByText("Needs a fix")).toBeVisible({ timeout: 180_000 });
  await expect(page.getByText("broken.py: syntax error on line 2: expected ':'")).toBeVisible();
  await expect(page.getByRole("button", { name: "Run backtest" })).toBeDisabled();

  await page.getByRole("button", { name: "Remove broken.py" }).click();
  await expect(page.getByText("Add at least one strategy file to run.")).toBeVisible();
});

test("cancels a run and returns to the form", async ({ page }) => {
  await startQuickRun(page, "amethyst_mm.py");
  await expect(page.getByRole("button", { name: "Cancel" })).toBeVisible();
  await page.getByRole("button", { name: "Cancel" }).click();
  await expect(page.getByText("Run cancelled.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Run backtest" })).toBeEnabled();
  await expect(page).toHaveURL(/\/$/);
});
