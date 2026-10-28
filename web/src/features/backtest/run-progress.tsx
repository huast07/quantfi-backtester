"use client";

import { useEffect, useState } from "react";

import ui from "@/components/ui.module.css";
import { caseInfo } from "@/lib/catalog";
import { formatDuration } from "@/lib/format";
import { jobKey, type Progress } from "@/lib/suite-run";
import type { SuiteSpec } from "@/py/types";
import type { PoolStatus } from "@/worker/pool";

import styles from "./backtest.module.css";

const TICK_MS = 1000;

interface Props {
  suite: SuiteSpec;
  strategyCount: number;
  progress: Progress | null;
  pool: PoolStatus | null;
  startedAt: number;
  /** When the first job started running, for a rate that leaves out the runtime download. */
  firstJobAt: number | null;
  onCancel: () => void;
}

function headline(progress: Progress | null, pool: PoolStatus | null): string {
  if (progress?.phase === "report") return "Scoring the results";
  const working = (pool?.busy ?? 0) + (progress?.done ?? 0);
  if (working === 0) return "Starting Python in your browser";
  return `Simulated ${progress?.done ?? 0} of ${progress?.total ?? 0} days`;
}

export function RunProgress({ suite, strategyCount, progress, pool, startedAt, firstJobAt, onCancel }: Props) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), TICK_MS);
    return () => clearInterval(timer);
  }, []);

  const done = progress?.done ?? 0;
  const total = progress?.total ?? suite.case_ids.length * suite.seeds.length;
  const remaining =
    firstJobAt !== null && done > 0 && done < total ? ((now - firstJobAt) / done) * (total - done) : null;
  const booting = (pool?.busy ?? 0) === 0 && done === 0;

  return (
    <section className={`${ui.panel} ${styles.progressPanel}`} aria-live="polite">
      <div className={styles.progressHead}>
        <div>
          <h2 className={styles.progressTitle}>{headline(progress, pool)}</h2>
          <p className={`${ui.small} ${ui.muted}`}>
            {booting
              ? "The first run downloads the Python runtime (about 40 MB); later runs start at once."
              : `${strategyCount + 1} strategies per day, including the reference, on ${pool?.size ?? 1} workers.`}
          </p>
        </div>
        <button type="button" className={`${ui.button} ${ui.danger}`} onClick={onCancel}>
          Cancel
        </button>
      </div>

      <div
        className={styles.bar}
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={done}
        aria-label="Days simulated"
      >
        <div className={styles.barFill} style={{ width: `${(done / Math.max(total, 1)) * 100}%` }} />
      </div>
      <div className={`${styles.progressMeta} ${ui.small} ${ui.muted}`}>
        <span className="num">Elapsed {formatDuration(now - startedAt)}</span>
        {remaining !== null && <span className="num">About {formatDuration(remaining)} left</span>}
      </div>

      <ul className={styles.caseGrid} aria-label="Progress per case">
        {suite.case_ids.map((caseId) => (
          <li key={caseId} className={styles.caseCell}>
            <span className={styles.caseName} title={caseInfo(caseId)?.title ?? caseId}>
              {caseInfo(caseId)?.title ?? caseId}
            </span>
            <span className={styles.seeds}>
              {suite.seeds.map((seed) => {
                const state = progress?.states[jobKey(caseId, seed)] ?? "queued";
                return (
                  <span
                    key={seed}
                    className={`${styles.seed} ${styles[`seed_${state}`]}`}
                    title={`Seed ${seed}: ${state}`}
                    aria-label={`Seed ${seed} ${state}`}
                  />
                );
              })}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
