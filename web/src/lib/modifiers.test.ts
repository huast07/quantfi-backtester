import { describe, expect, it } from "vitest";

import { eventWindowText, modifierParams } from "./modifiers";

describe("modifierParams", () => {
  it("formats ranges, lists and flags and skips unset values", () => {
    // Arrange
    const modifier = {
      kind: "shock",
      products: ["FRUIT_BASKET", "JELLY"],
      size: [150, 300],
      relative: false,
      recovery: 1,
      pick: null,
      delay_ticks: 0.25,
    };

    // Act
    const params = modifierParams(modifier);

    // Assert
    expect(params).toEqual([
      ["products", "FRUIT_BASKET, JELLY"],
      ["size", "150 to 300"],
      ["recovery", "1"],
      ["delay ticks", "0.25"],
    ]);
  });

  it("flattens nested objects and keeps true flags", () => {
    expect(modifierParams({ kind: "regime", scale: { AMETHYST: 2 }, per_product_size: true })).toEqual([
      ["scale", "AMETHYST 2"],
      ["per product size", "true"],
    ]);
  });
});

describe("eventWindowText", () => {
  it("states the window as a share of the day", () => {
    expect(eventWindowText([0.1, 0.4])).toBe("10% to 40% of the day");
  });
});
