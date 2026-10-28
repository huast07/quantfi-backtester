// The case catalog, written at build time by scripts/build_python.py from quantgen.browser.catalog(), so pages that
// only describe cases render without booting Python.
import data from "@/generated/catalog.json";
import { TIERS, type CaseInfo, type Catalog, type SuiteSpec, type Tier } from "@/py/types";

export const catalog = data as unknown as Catalog;

const byId = new Map(catalog.cases.map((c) => [c.id, c]));

export function caseInfo(id: string): CaseInfo | undefined {
  return byId.get(id);
}

export const SUITE_NAMES = ["quick", "standard", "full"] as const;
export type SuiteName = (typeof SUITE_NAMES)[number];

/** A named suite with its cases spelled out (Python's `None` means every case, in catalog order). */
export function namedSuite(name: SuiteName): SuiteSpec {
  const suite = catalog.suites[name];
  return { name, case_ids: suite.case_ids ?? catalog.cases.map((c) => c.id), seeds: suite.seeds };
}

export function customSuite(caseIds: string[], seedCount: number): SuiteSpec {
  const chosen = new Set(caseIds);
  return {
    name: "custom",
    case_ids: catalog.cases.filter((c) => chosen.has(c.id)).map((c) => c.id),
    seeds: Array.from({ length: seedCount }, (_, i) => i + 1),
  };
}

/** Items grouped by tier in tier order, keeping their order within a tier. */
export function groupByTier<T>(items: T[], tierOf: (item: T) => Tier): Array<{ tier: Tier; items: T[] }> {
  return TIERS.map((tier) => ({ tier, items: items.filter((item) => tierOf(item) === tier) })).filter(
    (group) => group.items.length > 0,
  );
}
