import { describe, expect, test } from "vitest";

import { fixture } from "@/test/fixture";

import { headToHead, overallScore, productBreakdown, profile, tierWeighted } from "./scoring";

const { report, catalog } = fixture;
const DEFAULT_WEIGHTS = { observed: 0.6, plausible: 0.3, stress: 0.1 };

describe("tierWeighted", () => {
  test.each(Object.keys(report.stats))("equals Python's weighted score for %s with the default weights", (name) => {
    expect(tierWeighted(report.stats[name], DEFAULT_WEIGHTS)).toBeCloseTo(report.overall[name].weighted_pnl, 9);
  });

  test("weights are relative: scaling them all changes nothing", () => {
    const stats = report.stats["fades.py"];
    const scaled = { observed: 6, plausible: 3, stress: 1 };
    expect(tierWeighted(stats, scaled)).toBeCloseTo(tierWeighted(stats, DEFAULT_WEIGHTS), 9);
  });

  test("putting all weight on one tier gives that tier's mean", () => {
    const stats = report.stats["fades.py"];
    const stress = stats.filter((s) => s.tier === "stress");
    const expected = stress.reduce((sum, s) => sum + s.mean_pnl, 0) / stress.length;
    expect(tierWeighted(stats, { observed: 0, plausible: 0, stress: 1 })).toBeCloseTo(expected, 9);
  });

  test("tiers absent from the suite hand their weight to the others", () => {
    const observedOnly = report.stats["fades.py"].filter((s) => s.tier === "observed");
    const expected = observedOnly.reduce((sum, s) => sum + s.mean_pnl, 0) / observedOnly.length;
    expect(tierWeighted(observedOnly, DEFAULT_WEIGHTS)).toBeCloseTo(expected, 9);
  });

  test("rejects weights that give the suite's tiers nothing", () => {
    const observedOnly = report.stats["fades.py"].filter((s) => s.tier === "observed");
    expect(() => tierWeighted(observedOnly, { observed: 0, plausible: 1, stress: 1 })).toThrow(RangeError);
  });
});

test("overallScore equals Python's overall for every strategy", () => {
  for (const [name, stats] of Object.entries(report.stats)) {
    const ours = overallScore(stats, DEFAULT_WEIGHTS);
    const theirs = report.overall[name];
    expect(ours.worst_case).toBe(theirs.worst_case);
    expect(ours.worst_case_pnl).toBe(theirs.worst_case_pnl);
    expect(ours.weighted_pnl).toBeCloseTo(theirs.weighted_pnl, 9);
  }
});

describe("profile", () => {
  const name = "amethyst_mm.py";
  const result = profile(report.verdicts[name], report.stats[name], catalog);

  test("lists strong cases best first and weak cases worst first, with their tiers", () => {
    expect(result.strong.map((entry) => entry.verdict.rating)).toEqual(["strong", "strong", "strong"]);
    const strongPnl = result.strong.map((entry) => entry.stats.mean_pnl);
    expect(strongPnl).toEqual([...strongPnl].sort((a, b) => b - a));
    expect(result.weak.map((entry) => entry.verdict.case_id).sort()).toEqual(["golden-continues", "regular-day"]);
    expect(result.weak[0].tier).toBeDefined();
  });

  test("counts ratings and products traded like the CLI", () => {
    expect(result.counts).toEqual({ strong: 3, neutral: 0, weak: 2 });
    expect(result.productsTraded).toBe(1);
    expect(profile(report.verdicts["fades.py"], report.stats["fades.py"], catalog).productsTraded).toBe(1);
  });
});

describe("headToHead", () => {
  const a = report.stats["amethyst_mm.py"];
  const b = report.stats["fades.py"];
  const result = headToHead(a, b);

  test("splits cases by who wins, biggest margins first", () => {
    expect(result.aWins.length + result.bWins.length + result.ties.length).toBe(a.length);
    expect(result.bWins).toEqual([]);
    const margins = result.aWins.map((row) => row.margin);
    expect(margins).toEqual([...margins].sort((x, y) => y - x));
    expect(result.aWins[0].margin).toBeCloseTo(a[4].mean_pnl - b[4].mean_pnl, 9);
  });

  test("counts the seeds each side was ahead on", () => {
    const row = result.aWins.find((r) => r.caseId === "black-swan-crash");
    expect(row).toMatchObject({ seedsAhead: 2, seedsBehind: 0, seeds: 2 });
  });

  test("is antisymmetric", () => {
    const reversed = headToHead(b, a);
    expect(reversed.bWins.map((row) => [row.caseId, -row.margin])).toEqual(
      result.aWins.map((row) => [row.caseId, row.margin]),
    );
  });
});

describe("productBreakdown", () => {
  const result = productBreakdown(report.stats["reference"]);

  test("has one row per case with a value for every product", () => {
    expect(result.rows.map((row) => row.caseId)).toEqual(report.stats["reference"].map((s) => s.case_id));
    for (const row of result.rows) {
      expect(Object.keys(row.pnl).sort()).toEqual([...result.products].sort());
    }
  });

  test("orders products by mean PnL across cases, best first, and totals them", () => {
    const means = result.products.map((product) => result.mean[product]);
    expect(means).toEqual([...means].sort((x, y) => y - x));
    const first = result.products[0];
    const expected = result.rows.reduce((sum, row) => sum + row.pnl[first], 0) / result.rows.length;
    expect(result.mean[first]).toBeCloseTo(expected, 9);
  });

  test("breadth counts products with any PnL", () => {
    expect(result.breadth).toBe(result.products.filter((p) => result.rows.some((row) => row.pnl[p] !== 0)).length);
    expect(result.breadth).toBeGreaterThan(10);
  });
});
