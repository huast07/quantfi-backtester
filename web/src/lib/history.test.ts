import { beforeEach, describe, expect, test } from "vitest";

import { fixture } from "@/test/fixture";
import { savedRun } from "@/test/saved-run";

import { deleteHistoryDatabase, exportRuns, openHistory, parseExport } from "./history";

const sample = savedRun;

beforeEach(async () => {
  await deleteHistoryDatabase();
});

describe("newSavedRun", () => {
  test("labels the run with its strategies and suite size", () => {
    const run = sample();
    expect(run.label).toBe("amethyst_mm.py vs fades.py, 5 cases x 2 seeds");
    expect(run.createdAt).toBe("2026-10-27T12:00:00.000Z");
    expect(run.id).toMatch(/^[0-9a-f-]{36}$/);
  });
});

describe("HistoryStore", () => {
  test("saves a run and reads it back unchanged", async () => {
    const history = await openHistory();
    const run = sample();
    await history.save(run);
    expect(await history.get(run.id)).toEqual(run);
    expect(await history.get("missing")).toBeUndefined();
  });

  test("lists summaries newest first, with each strategy's weighted score", async () => {
    const history = await openHistory();
    await history.save(sample({ id: "old", createdAt: "2026-10-01T00:00:00.000Z" }));
    await history.save(sample({ id: "new", createdAt: "2026-10-20T00:00:00.000Z" }));

    const list = await history.list();

    expect(list.map((summary) => summary.id)).toEqual(["new", "old"]);
    expect(list[0]).toMatchObject({
      label: "amethyst_mm.py vs fades.py, 5 cases x 2 seeds",
      cases: 5,
      seeds: 2,
      matchMode: "all",
      durationMs: 1234,
    });
    expect(list[0].scores).toEqual([
      { strategy: "amethyst_mm.py", weightedPnl: fixture.report.overall["amethyst_mm.py"].weighted_pnl },
      { strategy: "fades.py", weightedPnl: fixture.report.overall["fades.py"].weighted_pnl },
    ]);
  });

  test("removes a run and its summary", async () => {
    const history = await openHistory();
    const run = sample();
    await history.save(run);
    await history.remove(run.id);
    expect(await history.get(run.id)).toBeUndefined();
    expect(await history.list()).toEqual([]);
  });

  test("exports every run and imports them into an empty history", async () => {
    const history = await openHistory();
    await history.save(sample({ id: "a" }));
    await history.save(sample({ id: "b", createdAt: "2026-10-28T00:00:00.000Z" }));
    const text = await history.exportAll();

    await deleteHistoryDatabase();
    const fresh = await openHistory();
    expect(await fresh.importText(text)).toBe(2);
    expect((await fresh.list()).map((summary) => summary.id)).toEqual(["b", "a"]);
    expect(await fresh.get("a")).toEqual(sample({ id: "a" }));
  });
});

describe("parseExport", () => {
  const valid = () => JSON.parse(exportRuns([sample()]));

  test("accepts what exportRuns writes", () => {
    const run = sample();
    expect(parseExport(exportRuns([run]))).toEqual([run]);
  });

  test.each([
    ["not JSON", "{", /not valid JSON/],
    ["another file", JSON.stringify({ hello: 1 }), /not a backtest history export/],
    ["a newer format", JSON.stringify({ format: "quantgen-history", version: 2, runs: [] }), /version 2/],
  ])("rejects %s", (_, text, message) => {
    expect(() => parseExport(text)).toThrow(message);
  });

  test("names the run and field that is wrong", () => {
    const data = valid();
    data.runs[0].plan.strategies[0].source = 42;
    expect(() => parseExport(JSON.stringify(data))).toThrow(/run 1: plan\.strategies\[0\]\.source must be a string/);
  });

  test("rejects runs whose report does not cover its strategies", () => {
    const data = valid();
    delete data.runs[0].report.stats["fades.py"];
    expect(() => parseExport(JSON.stringify(data))).toThrow(/run 1: report has no stats for fades\.py/);
  });

  test("rejects malformed run metrics", () => {
    const data = valid();
    data.runs[0].runs[3].total_pnl = "lots";
    expect(() => parseExport(JSON.stringify(data))).toThrow(/run 1: runs\[3\]\.total_pnl must be a number/);
  });
});
