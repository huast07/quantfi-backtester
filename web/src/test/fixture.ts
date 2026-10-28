// Real quantgen.browser output (CPython) for 5 cases x 2 seeds, two uploads plus the reference.
// Regenerate with `uv run --project .. python scripts/fixture/make_report_fixture.py` from web/.
import type { CaseInfo, Report, RunMetrics, StrategyFile, SuiteSpec } from "@/py/types";

import data from "./fixtures/report.json";

interface Fixture {
  suite: SuiteSpec;
  strategies: StrategyFile[];
  runs: RunMetrics[];
  report: Report;
  catalog: CaseInfo[];
}

export const fixture: Fixture = {
  suite: data.suite,
  strategies: data.strategies,
  runs: data.runs as RunMetrics[],
  report: data.report as unknown as Report,
  catalog: data.cases as unknown as CaseInfo[],
};
