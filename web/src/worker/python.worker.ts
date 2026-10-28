/// <reference lib="webworker" />
// One Pyodide runtime with quantgen installed. Boots on start, then answers calls one at a time.
import type { PyodideAPI } from "pyodide";

import { bootQuantgen, type Quantgen } from "@/py/bootstrap";
import { PY_BUNDLE_PATH, PYODIDE_INDEX_URL } from "@/py/packages";

import type { WorkerRequest, WorkerResponse } from "./protocol";

declare const self: DedicatedWorkerGlobalScope;

const bundleUrl = new URL(`/${PY_BUNDLE_PATH}`, self.location.origin);

function post(message: WorkerResponse): void {
  self.postMessage(message);
}

async function fetchFile(file: string, sha256?: string): Promise<Uint8Array> {
  const url = new URL(file, bundleUrl);
  // The content hash in the query makes each version its own cache entry, so a deploy never mixes old and new files.
  if (sha256) url.searchParams.set("v", sha256.slice(0, 16));
  const response = await fetch(url, { cache: sha256 ? "force-cache" : "no-cache" });
  if (!response.ok) throw new Error(`Could not download ${file} (HTTP ${response.status})`);
  return new Uint8Array(await response.arrayBuffer());
}

type LoadPyodide = (options: { indexURL: string }) => Promise<PyodideAPI>;

async function boot(): Promise<Quantgen> {
  // Pyodide 314 only runs in module workers, which is why scripts/build-worker.mjs bundles this file as ESM.
  const pyodideModule = (await import(/* @vite-ignore */ `${PYODIDE_INDEX_URL}pyodide.mjs`)) as {
    loadPyodide: LoadPyodide;
  };
  const pyodide = await pyodideModule.loadPyodide({ indexURL: PYODIDE_INDEX_URL });
  // Strategy prints are captured per tick by prosperity3bt; anything else is noise in the console.
  pyodide.setStdout({ batched: () => {} });
  pyodide.setStderr({ batched: () => {} });
  return bootQuantgen(pyodide, fetchFile);
}

const ready = boot();
ready.then(
  () => post({ type: "ready" }),
  (error: unknown) => post({ type: "boot-failed", error: error instanceof Error ? error.message : String(error) }),
);

self.onmessage = async (event: MessageEvent<WorkerRequest>) => {
  const { id, method, payload } = event.data;
  try {
    const python = await ready;
    post({ type: "result", id, result: await python.call(method, payload as never) });
  } catch (error) {
    post({ type: "error", id, error: error instanceof Error ? error.message : String(error) });
  }
};
