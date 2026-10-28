// Phase 4 exit criterion: the browser (Pyodide) returns exactly what CPython returns for the same request.
// Runs the real bundle from public/py (npm run build:py) in Node's Pyodide, and quantgen.browser under uv for CPython.
import { execFile } from "node:child_process";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { promisify } from "node:util";

import { loadPyodide } from "pyodide";
import { beforeAll, describe, expect, test } from "vitest";

import { bootQuantgen, type Quantgen } from "@/py/bootstrap";
import type { ApiMethod, PythonApi, RunMetrics } from "@/py/types";

const ROOT = path.resolve(__dirname, "../../..");
const BUNDLE = path.join(ROOT, "web/public/py");
const PARAMS = path.join(ROOT, "params/params.json");

const TAKES_AMETHYST = `
from datamodel import Order

class Trader:
    def run(self, state):
        depth = state.order_depths["AMETHYST"]
        position = state.position.get("AMETHYST", 0)
        print("position", position)
        if state.timestamp < 2_000 and position < 5 and depth.sell_orders:
            return {"AMETHYST": [Order("AMETHYST", min(depth.sell_orders), 1)]}, 0, ""
        return {}, 0, ""
`;
const FADES_TELLURIUM = `
import numpy as np
from datamodel import Order

class Trader:
    def run(self, state):
        depth = state.order_depths["TELLURIUM"]
        if not depth.buy_orders or not depth.sell_orders:
            return {}, 0, state.traderData
        mid = (max(depth.buy_orders) + min(depth.sell_orders)) / 2
        history = [float(x) for x in state.traderData.split(",") if x][-20:] + [mid]
        position = state.position.get("TELLURIUM", 0)
        orders = []
        if mid > np.mean(history) + 3 and position > -10:
            orders.append(Order("TELLURIUM", max(depth.buy_orders), -1))
        elif mid < np.mean(history) - 3 and position < 10:
            orders.append(Order("TELLURIUM", min(depth.sell_orders), 1))
        return {"TELLURIUM": orders}, 0, ",".join(map(str, history))
`;
const STRATEGIES = [
  { name: "takes.py", source: TAKES_AMETHYST },
  { name: "fades.py", source: FADES_TELLURIUM },
];
const CASE_ID = "tellurium-storm";
const SEED = 2;
const BOOT_TIMEOUT = 600_000;
const RUN_TIMEOUT = 300_000;

const exec = promisify(execFile);

async function cpython<M extends ApiMethod>(method: M, payload?: PythonApi[M]["payload"]): Promise<string> {
  const script = [
    "import sys",
    "from quantgen import browser",
    "browser.init(sys.argv[1])",
    "fn = getattr(browser, sys.argv[2])",
    "sys.stdout.write(fn(sys.argv[3]) if len(sys.argv) > 3 else fn())",
  ].join("\n");
  const args = ["run", "--project", ROOT, "python", "-c", script, PARAMS, method];
  const { stdout } = await exec("uv", payload === undefined ? args : [...args, JSON.stringify(payload)], {
    cwd: ROOT,
    maxBuffer: 256 * 1024 * 1024,
  });
  return stdout;
}

let python: Quantgen;

beforeAll(async () => {
  const pyodide = await loadPyodide();
  pyodide.setStdout({ batched: () => {} });
  python = await bootQuantgen(pyodide, (file) => readFile(path.join(BUNDLE, file)));
}, BOOT_TIMEOUT);

describe("Pyodide equals CPython", () => {
  test("catalog", async () => {
    expect(await python.call("catalog", undefined)).toBe(await cpython("catalog"));
  });

  test(
    "generated case data, byte for byte",
    async () => {
      const payload = { case_id: CASE_ID, seed: SEED };
      expect(await python.call("case_csv", payload)).toBe(await cpython("case_csv", payload));
    },
    RUN_TIMEOUT,
  );

  test(
    "suite runs and the report built from them",
    async () => {
      const request = {
        strategies: STRATEGIES,
        case_id: CASE_ID,
        seed: SEED,
        match_mode: "all" as const,
        reference: true,
      };

      const [browserRuns, cliRuns] = await Promise.all([
        python.call("run_case", request),
        cpython("run_case", request),
      ]);

      expect(browserRuns).toBe(cliRuns);
      const runs = JSON.parse(browserRuns) as RunMetrics[];
      expect(runs.map((run) => run.strategy)).toEqual(["takes.py", "fades.py", "reference"]);
      expect(runs.find((run) => run.strategy === "fades.py")?.own_trades).toBeGreaterThan(0);
      const report = {
        suite: { name: "custom", case_ids: [CASE_ID], seeds: [SEED] },
        strategies: STRATEGIES.map((s) => s.name),
        runs,
      };
      expect(await python.call("report", report)).toBe(await cpython("report", report));
    },
    RUN_TIMEOUT,
  );

  test(
    "drill-down traces under the conservative match mode",
    async () => {
      const request = { strategy: STRATEGIES[1], case_id: CASE_ID, seed: SEED, match_mode: "worse" as const };
      expect(await python.call("drill", request)).toBe(await cpython("drill", request));
    },
    RUN_TIMEOUT,
  );

  test("a bad upload gets the same message", async () => {
    const bad = { name: "bad.py", source: "import no_such_module_here\n" };
    const message = await python.call("check_strategy", bad);
    expect(message).toBe(await cpython("check_strategy", bad));
    expect(JSON.parse(message).ok).toBe(false);
  });
});

test("a Python exception surfaces as its final line, not a traceback", async () => {
  await expect(python.call("case_csv", { case_id: "no-such-case", seed: 1 })).rejects.toThrow(
    /^[A-Za-z]*Error: .*no-such-case/,
  );
});
