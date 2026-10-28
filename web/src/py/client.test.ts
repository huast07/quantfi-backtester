import { afterEach, describe, expect, test, vi } from "vitest";

import { PythonPool } from "@/worker/pool";

import { PythonClient, pythonClient } from "./client";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("PythonClient", () => {
  test("decodes JSON results and passes log text through", async () => {
    // Arrange
    const call = vi.fn(async (method: string) => (method === "visualizer_log" ? "Sandbox logs:\n" : '{"ok": true}'));
    const client = new PythonClient({ call } as unknown as PythonPool);
    const signal = new AbortController().signal;

    // Act
    const check = await client.call("check_strategy", { name: "a.py", source: "" }, { signal });
    const log = await client.call("visualizer_log", {
      strategy: { name: "a.py", source: "" },
      case_id: "regular-day",
      seed: 1,
      match_mode: "all",
    });

    // Assert
    expect(check).toEqual({ ok: true });
    expect(log).toBe("Sandbox logs:\n");
    expect(call).toHaveBeenCalledWith("check_strategy", { name: "a.py", source: "" }, { signal });
  });
});

describe("pythonClient", () => {
  test("shares one pool whose workers are module workers from the bundle", () => {
    // Arrange
    const created: Array<{ url: string; options: WorkerOptions }> = [];
    vi.stubGlobal(
      "Worker",
      class {
        onmessage = null;
        constructor(url: string, options: WorkerOptions) {
          created.push({ url, options });
        }
        postMessage() {}
        terminate() {}
      },
    );

    // Act
    const client = pythonClient();
    client.pool.warm(1);

    // Assert
    expect(pythonClient()).toBe(client);
    expect(client.pool).toBeInstanceOf(PythonPool);
    expect(created).toHaveLength(1);
    expect(created[0].url).toMatch(/^\/py\/worker-[0-9a-f]+\.mjs$/);
    expect(created[0].options).toEqual({ type: "module", name: "python" });
    client.pool.dispose();
  });
});
