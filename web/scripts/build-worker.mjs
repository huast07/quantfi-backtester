// Bundles src/worker/python.worker.ts into an ES module worker in public/py. Turbopack only emits classic workers
// (importScripts), and Pyodide 314 refuses to load in a classic worker, so the worker is built outside Next.
// The file name carries a content hash so a deploy never runs a cached old worker; src/generated/worker.json tells
// the page which file to start.
import { createHash } from "node:crypto";
import { mkdir, readdir, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { build } from "esbuild";

const WEB = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const OUT = path.join(WEB, "public", "py");
const GENERATED = path.join(WEB, "src", "generated");

const result = await build({
  entryPoints: [path.join(WEB, "src/worker/python.worker.ts")],
  tsconfig: path.join(WEB, "tsconfig.json"),
  bundle: true,
  format: "esm",
  platform: "browser",
  target: "es2022",
  minify: true,
  write: false,
  logLevel: "warning",
});
const code = result.outputFiles[0].contents;
const file = `worker-${createHash("sha256").update(code).digest("hex").slice(0, 12)}.mjs`;

await mkdir(OUT, { recursive: true });
for (const old of (await readdir(OUT)).filter((name) => /^worker-[0-9a-f]+\.mjs$/.test(name))) {
  await rm(path.join(OUT, old));
}
await writeFile(path.join(OUT, file), code);
await mkdir(GENERATED, { recursive: true });
await writeFile(path.join(GENERATED, "worker.json"), `${JSON.stringify({ file })}\n`);
console.log(`wrote web/public/py/${file} (${(code.length / 1024).toFixed(1)} KB)`);
