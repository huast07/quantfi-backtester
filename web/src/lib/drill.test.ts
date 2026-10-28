import { describe, expect, test } from "vitest";

import type { RunDetail } from "@/py/types";

import { defaultProduct, drillSeries } from "./drill";

const detail: RunDetail = {
  timestamps: [0, 100, 200, 300],
  total_pnl: [0, 1, 3, 2],
  product_pnl: { AMETHYST: 5, TOFFEE: -9 },
  products: [
    {
      product: "AMETHYST",
      mid: [10, 11, 12, 13],
      pnl: [0, 1, 2, 5],
      position: [0, 2, 2, -1],
      fills: [
        { timestamp: 100, price: 10.5, quantity: 1 },
        { timestamp: 100, price: 11.5, quantity: 1 },
        { timestamp: 300, price: 13, quantity: -3 },
      ],
    },
    { product: "TOFFEE", mid: [5, 5, 5, 5], pnl: [0, 0, 1, -9], position: [0, 0, 0, 0], fills: [] },
  ],
  logs: [],
  logs_truncated: false,
};

describe("drillSeries", () => {
  const series = drillSeries(detail, "AMETHYST");

  test("prices: mid plus buy and sell markers at their tick, averaging fills that share one", () => {
    expect(series.price).toEqual([
      [0, 100, 200, 300],
      [10, 11, 12, 13],
      [null, 11, null, null],
      [null, null, null, 13],
    ]);
  });

  test("position and PnL follow the product, with the total PnL alongside", () => {
    expect(series.position).toEqual([
      [0, 100, 200, 300],
      [0, 2, 2, -1],
    ]);
    expect(series.pnl).toEqual([
      [0, 100, 200, 300],
      [0, 1, 2, 5],
      [0, 1, 3, 2],
    ]);
  });

  test("counts buys and sells by lots", () => {
    expect(series.bought).toBe(2);
    expect(series.sold).toBe(3);
  });

  test("an unknown product is an error, not an empty chart", () => {
    expect(() => drillSeries(detail, "NOPE")).toThrow(/NOPE/);
  });
});

test("the default product is the one with the largest absolute PnL", () => {
  expect(defaultProduct(detail)).toBe("TOFFEE");
  expect(defaultProduct({ ...detail, products: [] })).toBeNull();
});
