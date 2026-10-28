// Runs a suite in the browser the way quantgen.scoring.run_suite does on the CLI: one job per (case, seed), each job
// generating the day once and running every strategy plus the reference on it, then one report over all runs.
import type { CallOptions } from "@/worker/pool";
import { abortError, isAbortError } from "@/worker/pool";
import type { ApiMethod, MatchMode, PythonApi, Report, RunMetrics, StrategyFile, SuiteSpec } from "@/py/types";

export interface SuitePlan {
  suite: SuiteSpec;
  strategies: StrategyFile[];
  matchMode: MatchMode;
}

export type JobState = "queued" | "running" | "done";

export interface Progress {
  phase: "runs" | "report";
  total: number;
  done: number;
  /** Keyed by `jobKey(caseId, seed)`. */
  states: Record<string, JobState>;
}

export interface SuiteOutcome {
  runs: RunMetrics[];
  report: Report;
}

export interface Caller {
  call<M extends ApiMethod>(
    method: M,
    payload: PythonApi[M]["payload"],
    options?: CallOptions,
  ): Promise<PythonApi[M]["result"]>;
}

export interface RunOptions {
  signal?: AbortSignal;
  onProgress?: (progress: Progress) => void;
}

export const jobKey = (caseId: string, seed: number): string => `${caseId}:${seed}`;

interface Job {
  caseId: string;
  seed: number;
}

function planJobs(suite: SuiteSpec): Job[] {
  return suite.case_ids.flatMap((caseId) => suite.seeds.map((seed) => ({ caseId, seed })));
}

export async function runSuite(
  client: Caller,
  plan: SuitePlan,
  { signal, onProgress }: RunOptions = {},
): Promise<SuiteOutcome> {
  if (signal?.aborted) throw abortError();
  const jobs = planJobs(plan.suite);
  // A controller per call (one listener each, however large the suite), all stopped together on failure or cancel.
  const controllers = new Set<AbortController>();
  let stopped = false;
  const stop = () => {
    stopped = true;
    for (const controller of controllers) controller.abort();
  };
  const track = async <T>(call: (signal: AbortSignal) => Promise<T>): Promise<T> => {
    const controller = new AbortController();
    if (stopped) controller.abort();
    controllers.add(controller);
    try {
      return await call(controller.signal);
    } finally {
      controllers.delete(controller);
    }
  };
  signal?.addEventListener("abort", stop, { once: true });

  let progress: Progress = {
    phase: "runs",
    total: jobs.length,
    done: 0,
    states: Object.fromEntries(jobs.map((job) => [jobKey(job.caseId, job.seed), "queued" as JobState])),
  };
  const update = (key: string, state: JobState, phase: Progress["phase"] = "runs") => {
    progress = {
      phase,
      total: progress.total,
      done: progress.done + (state === "done" ? 1 : 0),
      states: { ...progress.states, [key]: state },
    };
    onProgress?.(progress);
  };
  onProgress?.(progress);

  try {
    const results = await Promise.all(
      jobs.map(async (job) => {
        const key = jobKey(job.caseId, job.seed);
        const request = {
          strategies: plan.strategies,
          case_id: job.caseId,
          seed: job.seed,
          match_mode: plan.matchMode,
          reference: true,
        };
        try {
          const runs = await track((jobSignal) =>
            client.call("run_case", request, { signal: jobSignal, onStart: () => update(key, "running") }),
          );
          update(key, "done");
          return runs;
        } catch (error) {
          stop();
          if (isAbortError(error) || signal?.aborted) throw abortError();
          throw new Error(`${job.caseId}, seed ${job.seed}: ${error instanceof Error ? error.message : String(error)}`);
        }
      }),
    );
    // Promise.all keeps job order, which is suite order: case, then seed, then strategy as Python returns them.
    const runs = results.flat();
    progress = { ...progress, phase: "report" };
    onProgress?.(progress);
    const report = await track((reportSignal) =>
      client.call(
        "report",
        { suite: plan.suite, strategies: plan.strategies.map((s) => s.name), runs },
        { signal: reportSignal },
      ),
    );
    return { runs, report };
  } catch (error) {
    if (signal?.aborted) throw abortError();
    throw error;
  } finally {
    signal?.removeEventListener("abort", stop);
  }
}
