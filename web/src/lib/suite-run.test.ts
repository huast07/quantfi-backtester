import { describe, expect, test } from "vitest";

import type { CallOptions } from "@/worker/pool";
import { abortError } from "@/worker/pool";
import type { ApiMethod, PythonApi, RunCaseRequest, RunMetrics } from "@/py/types";
import { fixture } from "@/test/fixture";

import { jobKey, runSuite, type Progress, type SuitePlan } from "./suite-run";

const plan: SuitePlan = { suite: fixture.suite, strategies: fixture.strategies, matchMode: "all" };

interface Call {
  method: ApiMethod;
  payload: unknown;
  options?: CallOptions;
  resolve: (value: unknown) => void;
  reject: (error: Error) => void;
}

/** A client whose calls stay pending until the test settles them, in any order. */
class ManualClient {
  calls: Call[] = [];

  call<M extends ApiMethod>(method: M, payload: PythonApi[M]["payload"], options?: CallOptions) {
    return new Promise<PythonApi[M]["result"]>((resolve, reject) => {
      const call = { method, payload, options, resolve: resolve as (value: unknown) => void, reject };
      this.calls.push(call);
      options?.signal?.addEventListener("abort", () => reject(abortError()), { once: true });
    });
  }

  runCases(): Call[] {
    return this.calls.filter((call) => call.method === "run_case");
  }

  answer(call: Call) {
    const { case_id, seed } = call.payload as RunCaseRequest;
    call.options?.onStart?.();
    call.resolve(fixture.runs.filter((run) => run.case_id === case_id && run.seed === seed));
  }
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("runSuite", () => {
  test("runs every case and seed once with every strategy and the reference", async () => {
    const client = new ManualClient();
    const outcome = runSuite(client, plan);
    await flush();

    const requests = client.runCases().map((call) => call.payload as RunCaseRequest);
    expect(requests).toHaveLength(fixture.suite.case_ids.length * fixture.suite.seeds.length);
    expect(new Set(requests.map((r) => jobKey(r.case_id, r.seed))).size).toBe(requests.length);
    expect(requests.every((r) => r.reference && r.match_mode === "all" && r.strategies === plan.strategies)).toBe(true);

    client.runCases().forEach((call) => client.answer(call));
    await flush();
    const report = client.calls.find((call) => call.method === "report");
    report?.resolve(fixture.report);

    await expect(outcome).resolves.toEqual({ runs: fixture.runs, report: fixture.report });
  });

  test("asks for the report with runs in suite order, whatever order the jobs finish in", async () => {
    const client = new ManualClient();
    const outcome = runSuite(client, plan);
    await flush();
    client
      .runCases()
      .toReversed()
      .forEach((call) => client.answer(call));
    await flush();

    const report = client.calls.find((call) => call.method === "report");
    expect(report?.payload).toEqual({
      suite: fixture.suite,
      strategies: ["amethyst_mm.py", "fades.py"],
      runs: fixture.runs,
    });
    report?.resolve(fixture.report);
    await outcome;
  });

  test("reports per-job progress: queued, running, done", async () => {
    const client = new ManualClient();
    const seen: Progress[] = [];
    const outcome = runSuite(client, plan, { onProgress: (progress) => seen.push(progress) });
    await flush();

    const first = seen[0];
    expect(first.total).toBe(10);
    expect(first.done).toBe(0);
    expect(Object.values(first.states).every((state) => state === "queued")).toBe(true);

    const call = client.runCases()[0];
    const { case_id, seed } = call.payload as RunCaseRequest;
    call.options?.onStart?.();
    expect(seen.at(-1)?.states[jobKey(case_id, seed)]).toBe("running");
    client.answer(call);
    await flush();
    expect(seen.at(-1)).toMatchObject({ done: 1 });
    expect(seen.at(-1)?.states[jobKey(case_id, seed)]).toBe("done");

    client
      .runCases()
      .slice(1)
      .forEach((c) => client.answer(c));
    await flush();
    expect(seen.at(-1)?.phase).toBe("report");
    client.calls.find((c) => c.method === "report")?.resolve(fixture.report);
    await outcome;
  });

  test("a failed job stops the suite and names the case and seed", async () => {
    const client = new ManualClient();
    const outcome = runSuite(client, plan);
    await flush();
    const [failing, ...rest] = client.runCases();
    failing.reject(new Error("The Python worker stopped (out of memory)."));

    await expect(outcome).rejects.toThrow(/regular-day, seed 1: The Python worker stopped/);
    expect(rest.every((call) => call.options?.signal?.aborted)).toBe(true);
    expect(client.calls.some((call) => call.method === "report")).toBe(false);
  });

  test("cancelling rejects with an AbortError and aborts every pending job", async () => {
    const client = new ManualClient();
    const controller = new AbortController();
    const outcome = runSuite(client, plan, { signal: controller.signal });
    await flush();
    controller.abort();

    await expect(outcome).rejects.toMatchObject({ name: "AbortError" });
    expect(client.runCases().every((call) => call.options?.signal?.aborted)).toBe(true);
  });

  test("strategy crashes are results, not failures", async () => {
    const client = new ManualClient();
    const crashed: RunMetrics = { ...fixture.runs[0], error: "ZeroDivisionError: division by zero" };
    const outcome = runSuite(client, { ...plan, suite: { ...plan.suite, case_ids: ["regular-day"], seeds: [1] } });
    await flush();
    client.runCases()[0].resolve([crashed]);
    await flush();
    client.calls.find((call) => call.method === "report")?.resolve(fixture.report);
    await expect(outcome).resolves.toMatchObject({ runs: [crashed] });
  });
});
