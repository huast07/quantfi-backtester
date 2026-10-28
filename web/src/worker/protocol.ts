// Messages between the page and a Pyodide worker. Payloads cross as JSON-compatible values; results as strings.
import type { ApiMethod } from "@/py/types";

export interface CallMessage {
  type: "call";
  id: number;
  method: ApiMethod;
  payload: unknown;
}

export type WorkerRequest = CallMessage;

export type WorkerResponse =
  | { type: "ready" }
  | { type: "boot-failed"; error: string }
  | { type: "result"; id: number; result: string }
  | { type: "error"; id: number; error: string };

/** The part of `Worker` the pool uses, so tests can drive it with a fake. */
export interface WorkerLike {
  postMessage(message: WorkerRequest): void;
  terminate(): void;
  onmessage: ((event: MessageEvent<WorkerResponse>) => void) | null;
  onerror: ((event: ErrorEvent) => void) | null;
}
