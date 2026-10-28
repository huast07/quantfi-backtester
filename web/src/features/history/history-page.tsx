"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import ui from "@/components/ui.module.css";
import { downloadText } from "@/lib/download";
import { formatDateTime, formatDuration, formatPnl } from "@/lib/format";
import { openHistory, type HistoryStore, type RunSummary } from "@/lib/history";

import styles from "./history.module.css";

type Listing = { state: "loading" } | { state: "ready"; runs: RunSummary[] } | { state: "error"; message: string };
type Notice = { tone: "info" | "error"; text: string } | null;

const errorMessage = (error: unknown) => (error instanceof Error ? error.message : String(error));

export function HistoryPage() {
  const store = useRef<HistoryStore | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const [listing, setListing] = useState<Listing>({ state: "loading" });
  const [notice, setNotice] = useState<Notice>(null);

  const refresh = async () => {
    const history = store.current ?? (store.current = await openHistory());
    setListing({ state: "ready", runs: await history.list() });
  };

  useEffect(() => {
    refresh().catch((error: unknown) => setListing({ state: "error", message: errorMessage(error) }));
  }, []);

  const act = async (task: (history: HistoryStore) => Promise<string | null>) => {
    try {
      const history = store.current ?? (store.current = await openHistory());
      const text = await task(history);
      await refresh();
      setNotice(text ? { tone: "info", text } : null);
    } catch (error) {
      setNotice({ tone: "error", text: errorMessage(error) });
    }
  };

  const remove = (run: RunSummary) => {
    if (!window.confirm(`Delete "${run.label}" from this browser? This cannot be undone.`)) return;
    void act(async (history) => {
      await history.remove(run.id);
      return "Run deleted.";
    });
  };

  const exportAll = () =>
    act(async (history) => {
      const stamp = new Date().toISOString().slice(0, 10);
      downloadText(`quantgen-history-${stamp}.json`, await history.exportAll(), "application/json");
      return null;
    });

  const importFile = (file: File) =>
    act(async (history) => {
      const count = await history.importText(await file.text());
      return `Imported ${count} ${count === 1 ? "run" : "runs"} from ${file.name}.`;
    });

  const runs = listing.state === "ready" ? listing.runs : [];

  return (
    <div className={ui.container}>
      <div className={`${ui.pageHeader} ${styles.header}`}>
        <div>
          <h1>History</h1>
          <p>
            Runs are saved in this browser only. Export them to keep a copy or move them to another machine; importing a
            file adds its runs and replaces any with the same id.
          </p>
        </div>
        <div className={styles.actions}>
          <input
            ref={fileInput}
            type="file"
            accept=".json,application/json"
            className="visually-hidden"
            tabIndex={-1}
            aria-hidden
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (file) void importFile(file);
            }}
          />
          <button type="button" className={`${ui.button} ${ui.buttonSmall}`} onClick={() => fileInput.current?.click()}>
            Import
          </button>
          <button
            type="button"
            className={`${ui.button} ${ui.buttonSmall}`}
            disabled={runs.length === 0}
            onClick={exportAll}
          >
            Export all
          </button>
        </div>
      </div>

      {notice && (
        <p className={`${ui.notice} ${notice.tone === "error" ? ui.error : ""} ${styles.notice}`} role="status">
          {notice.text}
        </p>
      )}

      {listing.state === "loading" && <p className={ui.empty}>Reading your saved runs.</p>}
      {listing.state === "error" && (
        <p className={`${ui.notice} ${ui.error}`} role="alert">
          Could not open the saved runs: {listing.message}
        </p>
      )}
      {listing.state === "ready" && runs.length === 0 && (
        <div className={`${ui.panel} ${ui.empty}`}>
          <p>No saved runs yet.</p>
          <p className={ui.small}>
            <Link href="/">Run a backtest</Link> and it will appear here.
          </p>
        </div>
      )}
      {runs.length > 0 && (
        <ul className={styles.list}>
          {runs.map((run) => (
            <li key={run.id} className={`${ui.panel} ${styles.run}`}>
              <div className={styles.runMain}>
                <Link href={`/results?id=${encodeURIComponent(run.id)}`} className={styles.runLabel} title={run.label}>
                  {run.scores.map((score) => score.strategy).join(" vs ")}
                </Link>
                <p className={ui.meta}>
                  <span>{formatDateTime(run.createdAt)}</span>
                  <span>
                    {run.suiteName} suite, {run.cases} cases x {run.seeds} {run.seeds === 1 ? "seed" : "seeds"}
                  </span>
                  <span>{run.matchMode} matching</span>
                  <span>{formatDuration(run.durationMs)}</span>
                </p>
              </div>
              <dl className={styles.scores}>
                {run.scores.map((score) => (
                  <div key={score.strategy} className={styles.score}>
                    <dt title={score.strategy}>{score.strategy}</dt>
                    <dd className={`num ${score.weightedPnl < 0 ? styles.negative : ""}`}>
                      {formatPnl(score.weightedPnl)}
                    </dd>
                  </div>
                ))}
              </dl>
              <div className={styles.runActions}>
                <Link href={`/results?id=${encodeURIComponent(run.id)}`} className={`${ui.button} ${ui.buttonSmall}`}>
                  Open
                </Link>
                <button
                  type="button"
                  className={`${ui.button} ${ui.ghost} ${ui.danger} ${ui.buttonSmall}`}
                  onClick={() => remove(run)}
                  aria-label={`Delete ${run.label}`}
                >
                  Delete
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
