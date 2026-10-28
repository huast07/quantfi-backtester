"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import ui from "@/components/ui.module.css";
import { usePoolStatus } from "@/components/use-python";
import { customSuite, namedSuite } from "@/lib/catalog";
import { newSavedRun, openHistory } from "@/lib/history";
import { addStrategyFiles, type IncomingFile, type Rejection, type StrategyEntry } from "@/lib/strategy-files";
import { runSuite, type Progress, type SuitePlan } from "@/lib/suite-run";
import { pythonClient } from "@/py/client";
import type { MatchMode } from "@/py/types";
import { isAbortError } from "@/worker/pool";

import styles from "./backtest.module.css";
import { RunProgress } from "./run-progress";
import { SuitePicker, type SuiteChoice } from "./suite-picker";
import { UploadPanel } from "./upload-panel";

type RunState =
  | { phase: "idle"; message: string | null }
  | { phase: "running"; plan: SuitePlan; startedAt: number; firstJobAt: number | null; progress: Progress | null }
  | { phase: "failed"; message: string };

const DEFAULT_CUSTOM_SEEDS = 2;

export function BacktestPage() {
  const router = useRouter();
  const pool = usePoolStatus();
  const [files, setFiles] = useState<StrategyEntry[]>([]);
  const [rejected, setRejected] = useState<Rejection[]>([]);
  const [choice, setChoice] = useState<SuiteChoice>("standard");
  const [customCases, setCustomCases] = useState<string[]>(() => namedSuite("quick").case_ids);
  const [customSeeds, setCustomSeeds] = useState(DEFAULT_CUSTOM_SEEDS);
  const [matchMode, setMatchMode] = useState<MatchMode>("all");
  const [run, setRun] = useState<RunState>({ phase: "idle", message: null });
  const controller = useRef<AbortController | null>(null);

  // Start one runtime while the visitor picks files, so the first check and run do not wait for the download.
  useEffect(() => pythonClient().pool.warm(1), []);
  useEffect(() => () => controller.current?.abort(), []);

  const setCheck = (name: string, check: StrategyEntry["check"]) =>
    setFiles((current) => current.map((f) => (f.name === name ? { ...f, check } : f)));

  const onAdd = (incoming: IncomingFile[]) => {
    const result = addStrategyFiles(files, incoming);
    setFiles(result.files);
    setRejected(result.rejected);
    const added = result.files.filter((f) => !files.includes(f));
    for (const file of added) {
      pythonClient()
        .call("check_strategy", { name: file.name, source: file.source })
        .then(
          (check) => setCheck(file.name, check.ok ? { state: "ok" } : { state: "error", message: check.error ?? "" }),
          (error: Error) => setCheck(file.name, { state: "error", message: error.message }),
        );
    }
  };

  const running = run.phase === "running";
  const ready = files.length > 0 && files.every((f) => f.check.state === "ok");
  const suite = choice === "custom" ? customSuite(customCases, customSeeds) : namedSuite(choice);
  const canRun = ready && !running && suite.case_ids.length > 0;

  const start = async () => {
    const plan: SuitePlan = { suite, strategies: files.map(({ name, source }) => ({ name, source })), matchMode };
    const abort = new AbortController();
    controller.current = abort;
    const startedAt = Date.now();
    setRun({ phase: "running", plan, startedAt, firstJobAt: null, progress: null });
    try {
      const outcome = await runSuite(pythonClient(), plan, {
        signal: abort.signal,
        onProgress: (progress) =>
          setRun((current) => {
            if (current.phase !== "running") return current;
            const started = Object.values(progress.states).some((state) => state !== "queued");
            return { ...current, progress, firstJobAt: current.firstJobAt ?? (started ? Date.now() : null) };
          }),
      });
      const saved = newSavedRun({ plan, outcome, durationMs: Date.now() - startedAt });
      await (await openHistory()).save(saved);
      router.push(`/results?id=${encodeURIComponent(saved.id)}`);
    } catch (error) {
      setRun(
        isAbortError(error)
          ? { phase: "idle", message: "Run cancelled." }
          : { phase: "failed", message: error instanceof Error ? error.message : String(error) },
      );
    } finally {
      controller.current = null;
    }
  };

  return (
    <div className={ui.container}>
      <div className={ui.pageHeader}>
        <h1>Backtest your strategies</h1>
        <p>
          Run one or more QuantiFi trader files on synthetic day-1 markets, each a named case from the literature, and
          see which cases each strategy handles well or badly. Everything runs in your browser.
        </p>
      </div>

      <div className={styles.layout}>
        <div className={styles.column}>
          {running ? (
            <RunProgress
              suite={run.plan.suite}
              strategyCount={run.plan.strategies.length}
              progress={run.progress}
              pool={pool}
              startedAt={run.startedAt}
              firstJobAt={run.firstJobAt}
              onCancel={() => controller.current?.abort()}
            />
          ) : (
            <>
              <UploadPanel
                files={files}
                rejected={rejected}
                disabled={running}
                onAdd={onAdd}
                onRemove={(name) => setFiles((current) => current.filter((f) => f.name !== name))}
              />
              <SuitePicker
                choice={choice}
                customCases={customCases}
                customSeeds={customSeeds}
                matchMode={matchMode}
                disabled={running}
                onChoice={setChoice}
                onCustomCases={setCustomCases}
                onCustomSeeds={setCustomSeeds}
                onMatchMode={setMatchMode}
              />
              {run.phase === "failed" && (
                <div className={`${ui.notice} ${ui.error}`} role="alert">
                  The run stopped: {run.message}
                </div>
              )}
              {run.phase === "idle" && run.message && <div className={ui.notice}>{run.message}</div>}
              <div className={styles.runBar}>
                <p className={`${ui.small} ${ui.muted}`}>
                  {files.length === 0
                    ? "Add at least one strategy file to run."
                    : suite.case_ids.length === 0
                      ? "Pick at least one case."
                      : `${files.length} ${files.length === 1 ? "strategy" : "strategies"} plus the reference on ${
                          suite.case_ids.length * suite.seeds.length
                        } simulated days.`}
                </p>
                <button
                  type="button"
                  className={`${ui.button} ${ui.primary} ${ui.large}`}
                  disabled={!canRun}
                  onClick={start}
                >
                  Run backtest
                </button>
              </div>
            </>
          )}
        </div>
        <HowItWorks />
      </div>
    </div>
  );
}

function HowItWorks() {
  return (
    <aside className={styles.aside} aria-label="How it works">
      <h2>How it works</h2>
      <ol>
        <li>
          Each case is a synthetic day 1 with a named situation: a regular day, a volatility crush, a crash. Every
          strategy sees the same days.
        </li>
        <li>A built-in reference market maker runs alongside, as a sanity gate rather than a score.</li>
        <li>
          Each strategy gets a profile: the cases it handles well, the ones it handles badly, and why, from its
          per-product PnL.
        </li>
      </ol>
      <p>Use Quick while iterating and Full before you submit. Results are saved in this browser under History.</p>
    </aside>
  );
}
