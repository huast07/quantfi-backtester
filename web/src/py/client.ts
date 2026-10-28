// Typed access to quantgen.browser through the worker pool: the payload goes in as a value, the result comes back
// decoded. One pool per page, created on first use.
import workerBuild from "@/generated/worker.json";
import { type CallOptions, defaultPoolSize, PythonPool } from "@/worker/pool";
import type { WorkerLike } from "@/worker/protocol";

import { PY_BUNDLE_PATH } from "./packages";
import type { ApiMethod, PythonApi } from "./types";

/** Methods whose result is plain text rather than JSON. */
const TEXT_RESULTS: ReadonlySet<ApiMethod> = new Set(["visualizer_log"]);

export class PythonClient {
  constructor(readonly pool: PythonPool) {}

  async call<M extends ApiMethod>(
    method: M,
    payload: PythonApi[M]["payload"],
    options?: CallOptions,
  ): Promise<PythonApi[M]["result"]> {
    const raw = await this.pool.call(method, payload, options);
    return (TEXT_RESULTS.has(method) ? raw : JSON.parse(raw)) as PythonApi[M]["result"];
  }
}

function createBrowserWorker(): WorkerLike {
  // Built by scripts/build-worker.mjs as an ES module (Pyodide 314 does not run in the classic workers Next emits).
  return new Worker(`/${PY_BUNDLE_PATH}${workerBuild.file}`, { type: "module", name: "python" });
}

let shared: PythonClient | null = null;

export function pythonClient(): PythonClient {
  if (!shared) {
    const memory = (navigator as Navigator & { deviceMemory?: number }).deviceMemory;
    shared = new PythonClient(
      new PythonPool(createBrowserWorker, defaultPoolSize(navigator.hardwareConcurrency, memory)),
    );
  }
  return shared;
}
