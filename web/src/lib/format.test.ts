import { describe, expect, test } from "vitest";

import { formatDuration, formatPercent, formatPnl, formatPrice, formatWhole } from "./format";

describe("format", () => {
  test("prints PnL as the CLI does", () => {
    expect(formatPnl(1234.4)).toBe("+1,234");
    expect(formatPnl(-56)).toBe("-56");
    expect(formatPnl(0)).toBe("0");
  });

  test("prints plain numbers, prices and shares", () => {
    expect(formatWhole(12345.6)).toBe("12,346");
    expect(formatPrice(10000.5)).toBe("10,000.5");
    expect(formatPercent(0.857)).toBe("86%");
  });

  test.each([
    [-500, "0 s"],
    [12_400, "12 s"],
    [125_000, "2 min 5 s"],
    [180_000, "3 min"],
    [1_500_000, "25 min"],
  ])("formats %d ms as %s", (ms, text) => {
    expect(formatDuration(ms)).toBe(text);
  });
});
