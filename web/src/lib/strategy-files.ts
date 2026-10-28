// Client-side checks on dropped files, before Python compiles them: type, size, unique names.

export const MAX_FILE_BYTES = 1024 * 1024;
/** Every strategy runs on every (case, seed) day, so run time grows with each one added. */
export const MAX_STRATEGIES = 6;

export type StrategyCheckState = { state: "checking" } | { state: "ok" } | { state: "error"; message: string };

export interface StrategyEntry {
  name: string;
  source: string;
  check: StrategyCheckState;
}

export interface IncomingFile {
  name: string;
  source: string;
  size: number;
}

export interface Rejection {
  name: string;
  reason: string;
}

export function addStrategyFiles(
  existing: StrategyEntry[],
  incoming: IncomingFile[],
): { files: StrategyEntry[]; rejected: Rejection[] } {
  return incoming.reduce(
    ({ files, rejected }, file) => {
      const reject = (reason: string) => ({ files, rejected: [...rejected, { name: file.name, reason }] });
      if (!file.name.toLowerCase().endsWith(".py")) return reject("is not a .py file");
      if (files.some((f) => f.name === file.name)) return reject("has the same name as a file already added");
      if (file.size === 0) return reject("is empty");
      if (file.size > MAX_FILE_BYTES) return reject("is larger than 1 MB");
      if (files.length >= MAX_STRATEGIES) return reject(`would exceed ${MAX_STRATEGIES} strategies per run`);
      const entry: StrategyEntry = { name: file.name, source: file.source, check: { state: "checking" } };
      return { files: [...files, entry], rejected };
    },
    { files: existing, rejected: [] as Rejection[] },
  );
}
