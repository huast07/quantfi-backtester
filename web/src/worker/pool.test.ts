import { describe, expect, test, vi } from "vitest";

import { defaultPoolSize, PythonPool, type PoolStatus } from "./pool";
import type { CallMessage, WorkerLike, WorkerRequest, WorkerResponse } from "./protocol";

class FakeWorker implements WorkerLike {
  posted: WorkerRequest[] = [];
  terminated = false;
  onmessage: ((event: MessageEvent<WorkerResponse>) => void) | null = null;
  onerror: ((event: ErrorEvent) => void) | null = null;

  postMessage(message: WorkerRequest) {
    this.posted.push(message);
  }

  terminate() {
    this.terminated = true;
  }

  send(data: WorkerResponse) {
    this.onmessage?.({ data } as MessageEvent<WorkerResponse>);
  }

  ready() {
    this.send({ type: "ready" });
  }

  lastCall(): CallMessage {
    const call = this.posted.at(-1);
    if (!call) throw new Error("nothing posted");
    return call;
  }

  answer(result: string) {
    this.send({ type: "result", id: this.lastCall().id, result });
  }

  crash(message: string) {
    this.onerror?.({ message } as ErrorEvent);
  }
}

function setup(size = 2) {
  const workers: FakeWorker[] = [];
  const pool = new PythonPool(() => {
    const worker = new FakeWorker();
    workers.push(worker);
    return worker;
  }, size);
  return { pool, workers };
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("PythonPool", () => {
  test("starts no worker until there is work", () => {
    const { workers } = setup();
    expect(workers).toHaveLength(0);
  });

  test("waits for a worker to boot, then runs the call and resolves with its result", async () => {
    const { pool, workers } = setup();
    const result = pool.call("case_csv", { case_id: "regular-day", seed: 1 });
    expect(workers).toHaveLength(1);
    expect(workers[0].posted).toHaveLength(0);

    workers[0].ready();
    expect(workers[0].lastCall()).toMatchObject({ method: "case_csv", payload: { case_id: "regular-day", seed: 1 } });
    workers[0].answer('{"day": 1}');

    await expect(result).resolves.toBe('{"day": 1}');
  });

  test("runs at most `size` calls at once and queues the rest in order", async () => {
    const { pool, workers } = setup(2);
    const results = [1, 2, 3].map((seed) => pool.call("case_csv", { case_id: "c", seed }));
    expect(workers).toHaveLength(2);
    workers.forEach((worker) => worker.ready());
    expect(workers.map((worker) => (worker.lastCall().payload as { seed: number }).seed)).toEqual([1, 2]);

    workers[1].answer("two");
    expect((workers[1].lastCall().payload as { seed: number }).seed).toBe(3);
    workers[1].answer("three");
    workers[0].answer("one");

    await expect(Promise.all(results)).resolves.toEqual(["one", "two", "three"]);
  });

  test("warm boots workers ahead of time without exceeding the size", () => {
    const { pool, workers } = setup(2);
    pool.warm(5);
    expect(workers).toHaveLength(2);
  });

  test("tells the caller when its call starts running", async () => {
    const { pool, workers } = setup(1);
    const started: string[] = [];
    pool.call("catalog", undefined, { onStart: () => started.push("first") });
    pool.call("catalog", undefined, { onStart: () => started.push("second") });
    expect(started).toEqual([]);
    workers[0].ready();
    expect(started).toEqual(["first"]);
    workers[0].answer("ok");
    expect(started).toEqual(["first", "second"]);
  });

  test("a Python error rejects only that call", async () => {
    const { pool, workers } = setup(1);
    const failing = pool.call("catalog", undefined);
    const next = pool.call("catalog", undefined);
    workers[0].ready();
    workers[0].send({ type: "error", id: workers[0].lastCall().id, error: "ValueError: bad" });
    await expect(failing).rejects.toThrow("ValueError: bad");
    workers[0].answer("ok");
    await expect(next).resolves.toBe("ok");
  });

  test("aborting a queued call removes it without posting it", async () => {
    const { pool, workers } = setup(1);
    const controller = new AbortController();
    const first = pool.call("catalog", undefined);
    const queued = pool.call("case_csv", { case_id: "c", seed: 1 }, { signal: controller.signal });

    controller.abort();
    await expect(queued).rejects.toMatchObject({ name: "AbortError" });
    workers[0].ready();
    workers[0].answer("first");
    await expect(first).resolves.toBe("first");
    expect(workers[0].posted).toHaveLength(1);
  });

  test("aborting a running call terminates its worker and a fresh one takes the next call", async () => {
    const { pool, workers } = setup(1);
    const controller = new AbortController();
    const running = pool.call("catalog", undefined, { signal: controller.signal });
    const next = pool.call("catalog", undefined);
    workers[0].ready();

    controller.abort();
    await expect(running).rejects.toMatchObject({ name: "AbortError" });
    expect(workers[0].terminated).toBe(true);
    expect(workers).toHaveLength(2);
    workers[1].ready();
    workers[1].answer("fresh");
    await expect(next).resolves.toBe("fresh");
  });

  test("an already aborted signal rejects at once", async () => {
    const { pool, workers } = setup(1);
    await expect(pool.call("catalog", undefined, { signal: AbortSignal.abort() })).rejects.toMatchObject({
      name: "AbortError",
    });
    expect(workers).toHaveLength(0);
  });

  test("a boot failure rejects the waiting calls, and a later call tries a new worker", async () => {
    const { pool, workers } = setup(1);
    const waiting = pool.call("catalog", undefined);
    workers[0].send({ type: "boot-failed", error: "network down" });
    await expect(waiting).rejects.toThrow("network down");
    expect(workers[0].terminated).toBe(true);

    const retry = pool.call("catalog", undefined);
    expect(workers).toHaveLength(2);
    workers[1].ready();
    workers[1].answer("ok");
    await expect(retry).resolves.toBe("ok");
  });

  test("a worker crash rejects its call and is replaced for the queue", async () => {
    const { pool, workers } = setup(1);
    const crashed = pool.call("catalog", undefined);
    const queued = pool.call("catalog", undefined);
    workers[0].ready();
    workers[0].crash("out of memory");
    await expect(crashed).rejects.toThrow(/out of memory/);
    expect(workers).toHaveLength(2);
    workers[1].ready();
    workers[1].answer("ok");
    await expect(queued).resolves.toBe("ok");
  });

  test("cancelAll rejects everything and stops busy workers, keeping booting and idle ones", async () => {
    const { pool, workers } = setup(3);
    pool.warm(3);
    workers[0].ready();
    workers[1].ready();
    const busy = pool.call("catalog", undefined);
    const queued = [pool.call("catalog", undefined), pool.call("catalog", undefined)];
    workers[1].answer("done");
    await expect(queued[0]).resolves.toBe("done");

    pool.cancelAll();

    await expect(busy).rejects.toMatchObject({ name: "AbortError" });
    await expect(queued[1]).rejects.toMatchObject({ name: "AbortError" });
    expect(workers.map((worker) => worker.terminated)).toEqual([true, true, false]);
    workers[2].ready();
    expect(pool.status()).toMatchObject({ idle: 1, busy: 0, booting: 0 });
  });

  test("reports booting, idle and busy counts to subscribers", async () => {
    const { pool, workers } = setup(2);
    const seen: PoolStatus[] = [];
    const unsubscribe = pool.subscribe((status) => seen.push(status));
    const call = pool.call("catalog", undefined);
    workers[0].ready();
    workers[0].answer("ok");
    await call;
    unsubscribe();
    pool.warm(2);

    expect(seen[0]).toEqual({ size: 2, booting: 0, idle: 0, busy: 0, error: null });
    expect(seen).toContainEqual({ size: 2, booting: 1, idle: 0, busy: 0, error: null });
    expect(seen).toContainEqual({ size: 2, booting: 0, idle: 0, busy: 1, error: null });
    expect(seen.at(-1)).toEqual({ size: 2, booting: 0, idle: 1, busy: 0, error: null });
  });

  test("remembers the last boot error for the status until a worker boots", async () => {
    const { pool, workers } = setup(1);
    const listener = vi.fn();
    pool.subscribe(listener);
    pool.call("catalog", undefined).catch(() => {});
    workers[0].send({ type: "boot-failed", error: "network down" });
    await flush();
    expect(listener).toHaveBeenLastCalledWith(expect.objectContaining({ error: "network down" }));
    pool.warm(1);
    workers[1].ready();
    expect(listener).toHaveBeenLastCalledWith(expect.objectContaining({ error: null, idle: 1 }));
  });

  test("dispose terminates every worker and rejects pending calls", async () => {
    const { pool, workers } = setup(2);
    const pending = pool.call("catalog", undefined);
    pool.dispose();
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
    expect(workers.every((worker) => worker.terminated)).toBe(true);
    await expect(pool.call("catalog", undefined)).rejects.toThrow(/disposed/);
  });
});

describe("defaultPoolSize", () => {
  test.each([
    [undefined, undefined, 2],
    [1, undefined, 1],
    [2, undefined, 1],
    [8, undefined, 4],
    [16, 16, 4],
    [8, 4, 2],
    [8, 2, 1],
  ])("%s cores and %s GB give %s workers", (cores, memory, expected) => {
    expect(defaultPoolSize(cores, memory)).toBe(expected);
  });
});
