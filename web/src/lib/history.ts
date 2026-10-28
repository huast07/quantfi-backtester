// Past runs, kept in the visitor's IndexedDB (no accounts, nothing on a server). Full runs and their list summaries
// live in separate stores, so the history page never loads every run's metrics just to draw the list.
import { deleteDB, openDB, type DBSchema, type IDBPDatabase } from "idb";

import type { MatchMode, Report, RunMetrics, StrategyFile, SuiteSpec } from "@/py/types";

import { EXPORT_FORMAT, EXPORT_VERSION, parseExport } from "./history-schema";
import type { SuiteOutcome, SuitePlan } from "./suite-run";

export { parseExport } from "./history-schema";

const DATABASE = "quantgen-history";
const DATABASE_VERSION = 1;

export interface SavedRun {
  version: 1;
  id: string;
  createdAt: string;
  label: string;
  plan: { suite: SuiteSpec; matchMode: MatchMode; strategies: StrategyFile[] };
  runs: RunMetrics[];
  report: Report;
  durationMs: number;
}

export interface RunSummary {
  id: string;
  createdAt: string;
  label: string;
  suiteName: string;
  cases: number;
  seeds: number;
  matchMode: MatchMode;
  durationMs: number;
  scores: Array<{ strategy: string; weightedPnl: number }>;
}

interface HistorySchema extends DBSchema {
  runs: { key: string; value: SavedRun };
  summaries: { key: string; value: RunSummary; indexes: { createdAt: string } };
}

export function newSavedRun({
  plan,
  outcome,
  durationMs,
  now = new Date(),
}: {
  plan: SuitePlan;
  outcome: SuiteOutcome;
  durationMs: number;
  now?: Date;
}): SavedRun {
  const names = plan.strategies.map((s) => s.name).join(" vs ");
  const size = `${plan.suite.case_ids.length} cases x ${plan.suite.seeds.length} seed${plan.suite.seeds.length === 1 ? "" : "s"}`;
  return {
    version: 1,
    id: crypto.randomUUID(),
    createdAt: now.toISOString(),
    label: `${names}, ${size}`,
    plan: { suite: plan.suite, matchMode: plan.matchMode, strategies: plan.strategies },
    runs: outcome.runs,
    report: outcome.report,
    durationMs,
  };
}

function summarize(run: SavedRun): RunSummary {
  return {
    id: run.id,
    createdAt: run.createdAt,
    label: run.label,
    suiteName: run.plan.suite.name,
    cases: run.plan.suite.case_ids.length,
    seeds: run.plan.suite.seeds.length,
    matchMode: run.plan.matchMode,
    durationMs: run.durationMs,
    scores: run.plan.strategies.map((s) => ({
      strategy: s.name,
      weightedPnl: run.report.overall[s.name].weighted_pnl,
    })),
  };
}

export function exportRuns(runs: SavedRun[]): string {
  return JSON.stringify({ format: EXPORT_FORMAT, version: EXPORT_VERSION, runs });
}

export interface HistoryStore {
  save(run: SavedRun): Promise<void>;
  get(id: string): Promise<SavedRun | undefined>;
  list(): Promise<RunSummary[]>;
  remove(id: string): Promise<void>;
  exportAll(): Promise<string>;
  /** Adds (or replaces, by id) every run in an export file. Returns how many were imported. */
  importText(text: string): Promise<number>;
}

async function saveAll(db: IDBPDatabase<HistorySchema>, runs: SavedRun[]): Promise<void> {
  const tx = db.transaction(["runs", "summaries"], "readwrite");
  await Promise.all([
    ...runs.map((run) => tx.objectStore("runs").put(run)),
    ...runs.map((run) => tx.objectStore("summaries").put(summarize(run))),
    tx.done,
  ]);
}

export async function openHistory(): Promise<HistoryStore> {
  const db = await openDB<HistorySchema>(DATABASE, DATABASE_VERSION, {
    upgrade(database) {
      database.createObjectStore("runs", { keyPath: "id" });
      database.createObjectStore("summaries", { keyPath: "id" }).createIndex("createdAt", "createdAt");
    },
    // Another tab (or a test) is upgrading or deleting the database: let it, rather than blocking it forever.
    blocking() {
      db.close();
    },
  });
  return {
    save: (run) => saveAll(db, [run]),
    get: (id) => db.get("runs", id),
    async list() {
      return (await db.getAllFromIndex("summaries", "createdAt")).toReversed();
    },
    async remove(id) {
      const tx = db.transaction(["runs", "summaries"], "readwrite");
      await Promise.all([tx.objectStore("runs").delete(id), tx.objectStore("summaries").delete(id), tx.done]);
    },
    async exportAll() {
      const runs = await db.getAll("runs");
      return exportRuns(runs.toSorted((a, b) => a.createdAt.localeCompare(b.createdAt)));
    },
    async importText(text) {
      const runs = parseExport(text);
      await saveAll(db, runs);
      return runs.length;
    },
  };
}

/** For tests: start from an empty history. */
export async function deleteHistoryDatabase(): Promise<void> {
  await deleteDB(DATABASE);
}
