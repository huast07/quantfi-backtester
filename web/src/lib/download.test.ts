import { afterEach, describe, expect, test, vi } from "vitest";

import { caseCsvNames, downloadText } from "./download";

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("downloadText", () => {
  test("saves the text through a temporary link and frees the URL later", async () => {
    // Arrange
    vi.useFakeTimers();
    URL.createObjectURL = vi.fn(() => "blob:report");
    URL.revokeObjectURL = vi.fn();
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      expect(this.download).toBe("report.txt");
      expect(this.href).toBe("blob:report");
    });

    // Act
    downloadText("report.txt", "PnL +12");

    // Assert
    expect(click).toHaveBeenCalledTimes(1);
    const blob = vi.mocked(URL.createObjectURL).mock.calls[0][0] as Blob;
    expect(blob.type).toBe("text/plain;charset=utf-8");
    expect(document.querySelector("a")).toBeNull();
    expect(URL.revokeObjectURL).not.toHaveBeenCalled();
    vi.runAllTimers();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:report");
  });
});

describe("caseCsvNames", () => {
  test("names the files like the competition's data", () => {
    expect(caseCsvNames("busy-day", 3, 1)).toEqual({
      prices: "busy-day_seed3_prices_round_1_day_1.csv",
      trades: "busy-day_seed3_trades_round_1_day_1.csv",
    });
  });
});
