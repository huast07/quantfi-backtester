import { newSavedRun, type SavedRun } from "@/lib/history";

import { fixture } from "./fixture";

/** The fixture as a saved run: two uploads plus the reference on 5 cases x 2 seeds. */
export function savedRun(overrides: Partial<SavedRun> = {}): SavedRun {
  return {
    ...newSavedRun({
      plan: { suite: fixture.suite, strategies: fixture.strategies, matchMode: "all" },
      outcome: { runs: fixture.runs, report: fixture.report },
      durationMs: 1234,
      now: new Date("2026-10-27T12:00:00Z"),
    }),
    ...overrides,
  };
}
