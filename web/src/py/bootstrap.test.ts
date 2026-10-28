// @vitest-environment node
import type { PyodideAPI } from "pyodide";
import { describe, expect, test, vi } from "vitest";

import {
  bootQuantgen,
  parseManifest,
  pythonErrorMessage,
  sha256Hex,
  strategySources,
  type FetchFile,
} from "./bootstrap";
import { PYODIDE_PACKAGES, PYODIDE_VERSION } from "./packages";

const encode = (text: string) => new TextEncoder().encode(text);

async function bundle(overrides: { version?: string; corruptParams?: boolean } = {}) {
  const wheel = encode("wheel bytes");
  const params = encode('{"products": {}}');
  const manifest = {
    pyodide: overrides.version ?? PYODIDE_VERSION,
    wheels: [{ file: "quantgen.whl", sha256: await sha256Hex(wheel) }],
    params: { file: "params.json", sha256: overrides.corruptParams ? "0".repeat(64) : await sha256Hex(params) },
  };
  const files: Record<string, Uint8Array> = {
    "manifest.json": encode(JSON.stringify(manifest)),
    "quantgen.whl": wheel,
    "params.json": params,
  };
  const fetchFile: FetchFile = vi.fn(async (file: string) => files[file]);
  return { fetchFile, manifest };
}

function fakePyodide() {
  const browser = {
    init: vi.fn(),
    catalog: vi.fn(() => '{"cases": []}'),
    check_strategy: vi.fn((json: string) => JSON.stringify({ ok: true, echo: JSON.parse(json).name })),
    run_case: vi.fn(() => {
      throw new Error('Traceback (most recent call last):\n  File "x.py"\nValueError: unknown case "nope"\n');
    }),
  };
  const pyodide = {
    version: PYODIDE_VERSION,
    loadPackage: vi.fn(async () => []),
    loadPackagesFromImports: vi.fn(async () => []),
    runPython: vi.fn(() => "/lib/python3/site-packages"),
    unpackArchive: vi.fn(),
    FS: { writeFile: vi.fn() },
    pyimport: vi.fn(() => browser),
  };
  return { pyodide, browser, api: pyodide as unknown as PyodideAPI };
}

describe("parseManifest", () => {
  test("accepts a well-formed manifest", () => {
    const text = JSON.stringify({
      pyodide: "1",
      wheels: [{ file: "a.whl", sha256: "x" }],
      params: { file: "p", sha256: "y" },
    });
    expect(parseManifest(text).wheels).toEqual([{ file: "a.whl", sha256: "x" }]);
  });

  test("rejects a manifest missing its checksums", () => {
    const text = JSON.stringify({ pyodide: "1", wheels: [{ file: "a.whl" }], params: { file: "p", sha256: "y" } });
    expect(() => parseManifest(text)).toThrow(/malformed/);
  });
});

describe("pythonErrorMessage", () => {
  test("keeps the last line of a traceback", () => {
    expect(pythonErrorMessage(new Error("Traceback:\n  line 1\nKeyError: 'x'\n\n"))).toBe("KeyError: 'x'");
    expect(pythonErrorMessage("")).toBe("Unknown Python error");
  });
});

describe("strategySources", () => {
  test("finds sources in every request shape", () => {
    expect(strategySources({ name: "a.py", source: "A" })).toEqual(["A"]);
    expect(strategySources({ strategy: { source: "B" } })).toEqual(["B"]);
    expect(strategySources({ strategies: [{ source: "C" }, { source: "D" }] })).toEqual(["C", "D"]);
    expect(strategySources(undefined)).toEqual([]);
  });
});

describe("bootQuantgen", () => {
  test("installs the verified bundle and calls quantgen.browser with JSON payloads", async () => {
    // Arrange
    const { fetchFile, manifest } = await bundle();
    const { pyodide, browser, api } = fakePyodide();

    // Act
    const quantgen = await bootQuantgen(api, fetchFile);
    const catalog = await quantgen.call("catalog", undefined);
    const check = await quantgen.call("check_strategy", { name: "a.py", source: "import numpy" });

    // Assert
    expect(fetchFile).toHaveBeenCalledWith("quantgen.whl", manifest.wheels[0].sha256);
    expect(pyodide.loadPackage).toHaveBeenCalledWith(PYODIDE_PACKAGES, expect.anything());
    expect(pyodide.unpackArchive).toHaveBeenCalledWith(expect.any(Uint8Array), "wheel", {
      extractDir: "/lib/python3/site-packages",
    });
    expect(pyodide.FS.writeFile).toHaveBeenCalledWith("/home/pyodide/params.json", expect.any(Uint8Array));
    expect(browser.init).toHaveBeenCalledWith("/home/pyodide/params.json");
    expect(catalog).toBe('{"cases": []}');
    expect(JSON.parse(check)).toEqual({ ok: true, echo: "a.py" });
    expect(pyodide.loadPackagesFromImports).toHaveBeenCalledWith("import numpy", expect.anything());
  });

  test("turns a Python traceback into its final line", async () => {
    const { fetchFile } = await bundle();
    const quantgen = await bootQuantgen(fakePyodide().api, fetchFile);
    await expect(
      quantgen.call("run_case", { strategies: [], case_id: "nope", seed: 1, match_mode: "all", reference: false }),
    ).rejects.toThrow('ValueError: unknown case "nope"');
  });

  test("refuses a bundle built for another Pyodide or with a bad checksum", async () => {
    const other = await bundle({ version: "0.0.1" });
    await expect(bootQuantgen(fakePyodide().api, other.fetchFile)).rejects.toThrow(/targets Pyodide 0\.0\.1/);
    const corrupt = await bundle({ corruptParams: true });
    await expect(bootQuantgen(fakePyodide().api, corrupt.fetchFile)).rejects.toThrow(/params\.json does not match/);
  });
});
