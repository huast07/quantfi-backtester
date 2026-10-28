// Validation for imported history files. Anything a user picks from disk is untrusted: every field the app reads
// is checked, and the first problem is reported with the run number and field path.
import { TIERS, type CaseStats, type MatchMode, type Overall, type RunMetrics, type Verdict } from "@/py/types";

import type { SavedRun } from "./history";

export const EXPORT_FORMAT = "quantgen-history";
export const EXPORT_VERSION = 1;
const MATCH_MODES: readonly MatchMode[] = ["all", "worse", "none"];
const RATINGS = ["strong", "neutral", "weak"];

class Invalid extends Error {}

type Value = unknown;

const fail = (path: string, message: string): never => {
  throw new Invalid(`${path} ${message}`);
};

function object(value: Value, path: string): Record<string, Value> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) fail(path, "must be an object");
  return value as Record<string, Value>;
}

function array(value: Value, path: string): Value[] {
  if (!Array.isArray(value)) fail(path, "must be a list");
  return value as Value[];
}

function string(value: Value, path: string): string {
  if (typeof value !== "string") fail(path, "must be a string");
  return value as string;
}

function number(value: Value, path: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) fail(path, "must be a number");
  return value as number;
}

function integer(value: Value, path: string): number {
  if (!Number.isInteger(value)) fail(path, "must be a whole number");
  return value as number;
}

function oneOf<T extends string>(value: Value, options: readonly T[], path: string): T {
  if (!options.includes(value as T)) fail(path, `must be one of ${options.join(", ")}`);
  return value as T;
}

function numberMap(value: Value, path: string): Record<string, number> {
  const data = object(value, path);
  for (const [key, item] of Object.entries(data)) number(item, `${path}.${key}`);
  return data as Record<string, number>;
}

function runMetrics(value: Value, path: string): RunMetrics {
  const data = object(value, path);
  string(data.strategy, `${path}.strategy`);
  string(data.case_id, `${path}.case_id`);
  integer(data.seed, `${path}.seed`);
  number(data.total_pnl, `${path}.total_pnl`);
  numberMap(data.product_pnl, `${path}.product_pnl`);
  number(data.max_drawdown, `${path}.max_drawdown`);
  integer(data.own_trades, `${path}.own_trades`);
  integer(data.limit_breaches, `${path}.limit_breaches`);
  if (data.error !== null) string(data.error, `${path}.error`);
  return data as unknown as RunMetrics;
}

function caseStats(value: Value, path: string): CaseStats {
  const data = object(value, path);
  string(data.strategy, `${path}.strategy`);
  string(data.case_id, `${path}.case_id`);
  oneOf(data.tier, TIERS, `${path}.tier`);
  numberMap(data.pnl_by_seed, `${path}.pnl_by_seed`);
  number(data.mean_pnl, `${path}.mean_pnl`);
  number(data.worst_pnl, `${path}.worst_pnl`);
  numberMap(data.product_mean_pnl, `${path}.product_mean_pnl`);
  number(data.mean_drawdown, `${path}.mean_drawdown`);
  integer(data.limit_breaches, `${path}.limit_breaches`);
  array(data.errors, `${path}.errors`).forEach((item, i) => string(item, `${path}.errors[${i}]`));
  return data as unknown as CaseStats;
}

function verdict(value: Value, path: string): Verdict {
  const data = object(value, path);
  string(data.strategy, `${path}.strategy`);
  string(data.case_id, `${path}.case_id`);
  oneOf(data.rating, RATINGS, `${path}.rating`);
  string(data.reason, `${path}.reason`);
  return data as unknown as Verdict;
}

function overall(value: Value, path: string): Overall {
  const data = object(value, path);
  number(data.weighted_pnl, `${path}.weighted_pnl`);
  string(data.worst_case, `${path}.worst_case`);
  number(data.worst_case_pnl, `${path}.worst_case_pnl`);
  return data as unknown as Overall;
}

function report(value: Value, strategies: string[], caseCount: number): void {
  const data = object(value, "report");
  const stats = object(data.stats, "report.stats");
  const verdicts = object(data.verdicts, "report.verdicts");
  const overalls = object(data.overall, "report.overall");
  if (typeof data.indicative !== "boolean") fail("report.indicative", "must be true or false");
  string(data.text, "report.text");
  for (const name of strategies) {
    if (!(name in stats)) throw new Invalid(`report has no stats for ${name}`);
    if (!(name in verdicts)) throw new Invalid(`report has no verdicts for ${name}`);
  }
  for (const [name, list] of Object.entries(stats)) {
    const items = array(list, `report.stats.${name}`);
    if (items.length !== caseCount) fail(`report.stats.${name}`, `must have one entry per case (${caseCount})`);
    items.forEach((item, i) => caseStats(item, `report.stats.${name}[${i}]`));
    overall(overalls[name], `report.overall.${name}`);
  }
  for (const [name, list] of Object.entries(verdicts)) {
    const items = array(list, `report.verdicts.${name}`);
    if (items.length !== caseCount) fail(`report.verdicts.${name}`, `must have one entry per case (${caseCount})`);
    items.forEach((item, i) => verdict(item, `report.verdicts.${name}[${i}]`));
  }
}

function savedRun(value: Value): SavedRun {
  const data = object(value, "run");
  if (data.version !== EXPORT_VERSION) fail("version", `must be ${EXPORT_VERSION}`);
  string(data.id, "id");
  if (Number.isNaN(Date.parse(string(data.createdAt, "createdAt")))) fail("createdAt", "must be a date");
  string(data.label, "label");
  number(data.durationMs, "durationMs");
  const plan = object(data.plan, "plan");
  const suite = object(plan.suite, "plan.suite");
  string(suite.name, "plan.suite.name");
  const caseIds = array(suite.case_ids, "plan.suite.case_ids").map((id, i) => string(id, `plan.suite.case_ids[${i}]`));
  array(suite.seeds, "plan.suite.seeds").forEach((seed, i) => integer(seed, `plan.suite.seeds[${i}]`));
  oneOf(plan.matchMode, MATCH_MODES, "plan.matchMode");
  const names = array(plan.strategies, "plan.strategies").map((item, i) => {
    const strategy = object(item, `plan.strategies[${i}]`);
    string(strategy.source, `plan.strategies[${i}].source`);
    return string(strategy.name, `plan.strategies[${i}].name`);
  });
  array(data.runs, "runs").forEach((item, i) => runMetrics(item, `runs[${i}]`));
  report(data.report, names, caseIds.length);
  return data as unknown as SavedRun;
}

/** The runs in an exported history file, or an Error saying what is wrong with it. */
export function parseExport(text: string): SavedRun[] {
  let data: Value;
  try {
    data = JSON.parse(text);
  } catch {
    throw new Error("This file is not valid JSON");
  }
  const file = typeof data === "object" && data !== null ? (data as Record<string, Value>) : {};
  if (file.format !== EXPORT_FORMAT) throw new Error("This file is not a backtest history export");
  if (file.version !== EXPORT_VERSION) {
    throw new Error(`This export is version ${String(file.version)}; this site reads version ${EXPORT_VERSION}`);
  }
  if (!Array.isArray(file.runs)) throw new Error("This export has no list of runs");
  return file.runs.map((run, index) => {
    try {
      return savedRun(run);
    } catch (error) {
      throw new Error(`run ${index + 1}: ${(error as Error).message}`);
    }
  });
}
