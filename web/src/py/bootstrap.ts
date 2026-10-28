// Installs the bundle from public/py into a Pyodide instance and exposes quantgen.browser. Shared by the web worker
// and the Node parity test, so the code path the test checks is the one the browser runs.
import type { PyodideAPI } from "pyodide";

import { PYODIDE_PACKAGES } from "./packages";
import type { ApiMethod, PythonApi } from "./types";

export interface BundleFile {
  file: string;
  sha256: string;
}

export interface Manifest {
  pyodide: string;
  wheels: BundleFile[];
  params: BundleFile;
}

/** Reads a file of the bundle by name. `sha256` lets a browser fetch bypass stale caches. */
export type FetchFile = (file: string, sha256?: string) => Promise<Uint8Array>;

export interface Quantgen {
  /** The raw JSON (or log text) the Python function returned. */
  call<M extends ApiMethod>(method: M, payload: PythonApi[M]["payload"]): Promise<string>;
}

const PARAMS_PATH = "/home/pyodide/params.json";

export async function sha256Hex(bytes: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", bytes as Uint8Array<ArrayBuffer>);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function fetchVerified(fetchFile: FetchFile, entry: BundleFile): Promise<Uint8Array> {
  const fetched = await fetchFile(entry.file, entry.sha256);
  // A plain view: Pyodide rejects Uint8Array subclasses such as Node's Buffer.
  const bytes = new Uint8Array(fetched.buffer, fetched.byteOffset, fetched.byteLength);
  const actual = await sha256Hex(bytes);
  if (actual !== entry.sha256) {
    throw new Error(`${entry.file} does not match its manifest checksum; reload the page to fetch it again`);
  }
  return bytes;
}

export function parseManifest(text: string): Manifest {
  const data = JSON.parse(text) as Partial<Manifest>;
  const isEntry = (value: unknown): value is BundleFile =>
    typeof value === "object" &&
    value !== null &&
    typeof (value as BundleFile).file === "string" &&
    typeof (value as BundleFile).sha256 === "string";
  if (
    typeof data.pyodide !== "string" ||
    !Array.isArray(data.wheels) ||
    !data.wheels.every(isEntry) ||
    !isEntry(data.params)
  ) {
    throw new Error("The Python bundle manifest is malformed; rebuild it with `npm run build:py`");
  }
  return { pyodide: data.pyodide, wheels: data.wheels, params: data.params };
}

/** Pyodide errors carry the whole traceback; the last line ("ValueError: ...") is what a user can act on. */
export function pythonErrorMessage(error: unknown): string {
  const text = error instanceof Error ? error.message : String(error);
  const lines = text
    .trim()
    .split("\n")
    .filter((line) => line.trim() !== "");
  return lines.at(-1)?.trim() ?? "Unknown Python error";
}

/** Strategy sources in a request, so the packages they import (numpy, pandas, ...) load before they run. */
export function strategySources(payload: unknown): string[] {
  if (typeof payload !== "object" || payload === null) return [];
  const data = payload as {
    source?: unknown;
    strategy?: { source?: unknown };
    strategies?: Array<{ source?: unknown }>;
  };
  const candidates = [data.source, data.strategy?.source, ...(data.strategies ?? []).map((s) => s.source)];
  return candidates.filter((source): source is string => typeof source === "string");
}

export async function bootQuantgen(pyodide: PyodideAPI, fetchFile: FetchFile): Promise<Quantgen> {
  const manifest = parseManifest(new TextDecoder().decode(await fetchFile("manifest.json")));
  if (manifest.pyodide !== pyodide.version) {
    throw new Error(`The Python bundle targets Pyodide ${manifest.pyodide}, but ${pyodide.version} is loaded`);
  }
  const quiet = { messageCallback: () => {} };
  const [, wheels, params] = await Promise.all([
    pyodide.loadPackage(PYODIDE_PACKAGES, quiet),
    Promise.all(manifest.wheels.map((wheel) => fetchVerified(fetchFile, wheel))),
    fetchVerified(fetchFile, manifest.params),
  ]);
  const sitePackages = pyodide.runPython("import sysconfig; sysconfig.get_paths()['purelib']") as string;
  for (const wheel of wheels) {
    pyodide.unpackArchive(wheel, "wheel", { extractDir: sitePackages });
  }
  pyodide.FS.writeFile(PARAMS_PATH, params);
  pyodide.runPython("import importlib; importlib.invalidate_caches()");
  const browser = pyodide.pyimport("quantgen.browser");
  browser.init(PARAMS_PATH);

  return {
    async call(method, payload) {
      for (const source of strategySources(payload)) {
        await pyodide.loadPackagesFromImports(source, quiet);
      }
      try {
        const result = payload === undefined ? browser[method]() : browser[method](JSON.stringify(payload));
        return result as string;
      } catch (error) {
        throw new Error(pythonErrorMessage(error));
      }
    },
  };
}
