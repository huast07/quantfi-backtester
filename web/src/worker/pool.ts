// A pool of Pyodide workers. Each worker runs one call at a time (Python is single-threaded), so the pool holds a
// FIFO queue and hands calls to idle workers. Python cannot be interrupted mid-call, so cancelling a running call
// terminates its worker; a fresh one boots when there is more work.
import type { ApiMethod } from "@/py/types";

import type { WorkerLike, WorkerResponse } from "./protocol";

const MAX_WORKERS = 4;
const ASSUMED_CORES = 3;
/** Each Pyodide worker with numpy and a day in memory needs roughly this much. */
const GB_PER_WORKER = 2;

export interface PoolStatus {
  size: number;
  booting: number;
  idle: number;
  busy: number;
  /** The last boot failure, until a worker boots successfully. */
  error: string | null;
}

type Listener = (status: PoolStatus) => void;

export interface CallOptions {
  signal?: AbortSignal;
  /** Called when a worker picks the call up, after it waited in the queue. */
  onStart?: () => void;
}

interface Job {
  id: number;
  method: ApiMethod;
  payload: unknown;
  resolve: (result: string) => void;
  reject: (error: Error) => void;
  release: () => void;
  onStart?: () => void;
}

interface Slot {
  worker: WorkerLike;
  state: "booting" | "idle" | "busy";
  job: Job | null;
}

export function abortError(): Error {
  return Object.assign(new Error("The run was cancelled"), { name: "AbortError" });
}

export function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === "AbortError";
}

/** One worker per spare core, capped by memory and by MAX_WORKERS. */
export function defaultPoolSize(cores?: number, memoryGb?: number): number {
  const byCores = Math.max((cores ?? ASSUMED_CORES) - 1, 1);
  const byMemory = memoryGb === undefined ? MAX_WORKERS : Math.max(Math.floor(memoryGb / GB_PER_WORKER), 1);
  return Math.min(byCores, byMemory, MAX_WORKERS);
}

export class PythonPool {
  private slots: Slot[] = [];
  private queue: Job[] = [];
  private listeners = new Set<Listener>();
  private nextId = 1;
  private lastError: string | null = null;
  /** Set after a boot failure so a broken network does not respawn workers in a loop; any new request clears it. */
  private spawnBlocked = false;
  private disposed = false;

  constructor(
    private readonly createWorker: () => WorkerLike,
    readonly size: number,
  ) {}

  call(method: ApiMethod, payload: unknown, { signal, onStart }: CallOptions = {}): Promise<string> {
    if (this.disposed) return Promise.reject(new Error("The Python pool was disposed"));
    if (signal?.aborted) return Promise.reject(abortError());
    return new Promise<string>((resolve, reject) => {
      const onAbort = () => this.abort(job);
      const job: Job = {
        id: this.nextId++,
        method,
        payload,
        resolve,
        reject,
        release: () => signal?.removeEventListener("abort", onAbort),
        onStart,
      };
      signal?.addEventListener("abort", onAbort, { once: true });
      this.queue.push(job);
      this.spawnBlocked = false;
      this.pump();
    });
  }

  /** Boot workers ahead of the first call, so the runtime download overlaps with choosing files. */
  warm(count: number): void {
    if (this.disposed) return;
    this.spawnBlocked = false;
    while (this.slots.length < Math.min(count, this.size)) this.spawn();
    this.emit();
  }

  cancelAll(): void {
    for (const job of this.queue.splice(0)) this.settle(job, abortError());
    for (const slot of this.slots.filter((s) => s.state === "busy")) {
      const job = slot.job;
      this.remove(slot);
      if (job) this.settle(job, abortError());
    }
    this.emit();
  }

  dispose(): void {
    this.cancelAll();
    for (const slot of [...this.slots]) this.remove(slot);
    this.disposed = true;
    this.emit();
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    listener(this.status());
    return () => {
      this.listeners.delete(listener);
    };
  }

  status(): PoolStatus {
    const count = (state: Slot["state"]) => this.slots.filter((slot) => slot.state === state).length;
    return {
      size: this.size,
      booting: count("booting"),
      idle: count("idle"),
      busy: count("busy"),
      error: this.lastError,
    };
  }

  private emit(): void {
    const status = this.status();
    for (const listener of this.listeners) listener(status);
  }

  private spawn(): void {
    const slot: Slot = { worker: this.createWorker(), state: "booting", job: null };
    slot.worker.onmessage = (event) => this.onMessage(slot, event.data);
    slot.worker.onerror = (event) => this.onCrash(slot, event.message || "unknown error");
    this.slots.push(slot);
  }

  private pump(): void {
    for (const slot of this.slots) {
      if (slot.state !== "idle" || this.queue.length === 0) continue;
      const job = this.queue.shift() as Job;
      slot.state = "busy";
      slot.job = job;
      slot.worker.postMessage({ type: "call", id: job.id, method: job.method, payload: job.payload });
      job.onStart?.();
    }
    let booting = this.slots.filter((slot) => slot.state === "booting").length;
    while (!this.spawnBlocked && this.queue.length > booting && this.slots.length < this.size) {
      this.spawn();
      booting += 1;
    }
    this.emit();
  }

  private onMessage(slot: Slot, message: WorkerResponse): void {
    if (!this.slots.includes(slot)) return;
    switch (message.type) {
      case "ready":
        slot.state = "idle";
        this.lastError = null;
        this.spawnBlocked = false;
        this.pump();
        return;
      case "boot-failed":
        this.onBootFailed(slot, message.error);
        return;
      case "result":
      case "error": {
        const job = slot.job;
        if (!job || job.id !== message.id) return;
        slot.state = "idle";
        slot.job = null;
        this.settle(job, message.type === "result" ? message.result : new Error(message.error));
        this.pump();
        return;
      }
    }
  }

  private onBootFailed(slot: Slot, error: string): void {
    this.remove(slot);
    this.lastError = error;
    this.spawnBlocked = true;
    if (this.slots.length === 0) {
      for (const job of this.queue.splice(0)) this.settle(job, new Error(error));
    }
    this.pump();
  }

  private onCrash(slot: Slot, message: string): void {
    if (!this.slots.includes(slot)) return;
    if (slot.state === "booting") {
      this.onBootFailed(slot, `The Python runtime failed to start: ${message}`);
      return;
    }
    const job = slot.job;
    this.remove(slot);
    if (job) this.settle(job, new Error(`The Python worker stopped (${message}). It may have run out of memory.`));
    this.pump();
  }

  private abort(job: Job): void {
    const queued = this.queue.indexOf(job);
    if (queued >= 0) {
      this.queue.splice(queued, 1);
    } else {
      const slot = this.slots.find((s) => s.job === job);
      if (!slot) return;
      this.remove(slot);
    }
    this.settle(job, abortError());
    this.pump();
  }

  private remove(slot: Slot): void {
    slot.worker.onmessage = null;
    slot.worker.onerror = null;
    slot.worker.terminate();
    this.slots = this.slots.filter((s) => s !== slot);
  }

  private settle(job: Job, outcome: string | Error): void {
    job.release();
    if (outcome instanceof Error) job.reject(outcome);
    else job.resolve(outcome);
  }
}
