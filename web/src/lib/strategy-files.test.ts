import { describe, expect, test } from "vitest";

import { addStrategyFiles, MAX_FILE_BYTES, MAX_STRATEGIES, type StrategyEntry } from "./strategy-files";

const file = (name: string, source = "class Trader: pass\n", size = source.length) => ({ name, source, size });
const entry = (name: string): StrategyEntry => ({ name, source: "", check: { state: "ok" } });

describe("addStrategyFiles", () => {
  test("adds Python files as entries waiting for their check", () => {
    const result = addStrategyFiles([], [file("a.py"), file("b.py")]);
    expect(result.files.map((f) => [f.name, f.check.state])).toEqual([
      ["a.py", "checking"],
      ["b.py", "checking"],
    ]);
    expect(result.rejected).toEqual([]);
  });

  test("keeps existing files and appends new ones", () => {
    const result = addStrategyFiles([entry("a.py")], [file("b.py")]);
    expect(result.files.map((f) => f.name)).toEqual(["a.py", "b.py"]);
    expect(result.files[0].check.state).toBe("ok");
  });

  test.each([
    ["notes.txt", "is not a .py file"],
    ["reference", "is not a .py file"],
  ])("rejects %s", (name, reason) => {
    expect(addStrategyFiles([], [file(name)]).rejected).toEqual([{ name, reason }]);
  });

  test("rejects a name that is already added, in either list", () => {
    const result = addStrategyFiles([entry("a.py")], [file("a.py"), file("b.py"), file("b.py")]);
    expect(result.files.map((f) => f.name)).toEqual(["a.py", "b.py"]);
    expect(result.rejected).toEqual([
      { name: "a.py", reason: "has the same name as a file already added" },
      { name: "b.py", reason: "has the same name as a file already added" },
    ]);
  });

  test("rejects empty and oversized files", () => {
    const result = addStrategyFiles([], [file("empty.py", "", 0), file("big.py", "x", MAX_FILE_BYTES + 1)]);
    expect(result.rejected).toEqual([
      { name: "empty.py", reason: "is empty" },
      { name: "big.py", reason: "is larger than 1 MB" },
    ]);
  });

  test("stops at the strategy limit", () => {
    const existing = Array.from({ length: MAX_STRATEGIES - 1 }, (_, i) => entry(`s${i}.py`));
    const result = addStrategyFiles(existing, [file("last.py"), file("extra.py")]);
    expect(result.files).toHaveLength(MAX_STRATEGIES);
    expect(result.rejected).toEqual([
      { name: "extra.py", reason: `would exceed ${MAX_STRATEGIES} strategies per run` },
    ]);
  });
});
