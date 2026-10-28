import { describe, expect, test } from "vitest";

import { caseInfo, catalog, customSuite, groupByTier, namedSuite } from "./catalog";

describe("catalog", () => {
  test("spells out the cases of suites that cover everything", () => {
    expect(namedSuite("full").case_ids).toEqual(catalog.cases.map((c) => c.id));
    expect(namedSuite("quick").case_ids).toEqual(catalog.suites.quick.case_ids);
  });

  test("keeps a custom suite in catalog order and drops unknown cases", () => {
    const [first, second] = catalog.cases;
    expect(customSuite([second.id, "not-a-case", first.id], 3)).toEqual({
      name: "custom",
      case_ids: [first.id, second.id],
      seeds: [1, 2, 3],
    });
  });

  test("looks cases up by id and groups them by tier", () => {
    expect(caseInfo("regular-day")?.tier).toBe("observed");
    expect(caseInfo("missing")).toBeUndefined();
    const groups = groupByTier(catalog.cases, (c) => c.tier);
    expect(groups.map((g) => g.tier)).toEqual(["observed", "plausible", "stress"]);
    expect(groups.reduce((n, g) => n + g.items.length, 0)).toBe(catalog.cases.length);
  });
});
