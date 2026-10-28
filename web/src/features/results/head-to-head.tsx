"use client";

import { useState } from "react";

import { TierBadge } from "@/components/badges";
import ui from "@/components/ui.module.css";
import { caseInfo } from "@/lib/catalog";
import { formatWhole } from "@/lib/format";
import { headToHead, type HeadToHeadRow } from "@/lib/scoring";
import type { Report } from "@/py/types";

import styles from "./results.module.css";

interface Props {
  strategies: string[];
  report: Report;
  onSelect: (strategy: string, caseId: string) => void;
}

function Side({
  winner,
  loser,
  rows,
  scale,
  onSelect,
}: {
  winner: string;
  loser: string;
  rows: HeadToHeadRow[];
  scale: number;
  onSelect: (caseId: string) => void;
}) {
  return (
    <div className={styles.h2hSide}>
      <h4 className={styles.listTitle}>
        <span className={styles.mono}>{winner}</span> ahead <span className={ui.faint}>{rows.length}</span>
      </h4>
      {rows.length === 0 ? (
        <p className={`${ui.small} ${ui.faint}`}>
          Never ahead of <span className={styles.mono}>{loser}</span>.
        </p>
      ) : (
        <ul>
          {rows.map((row) => {
            const margin = Math.abs(row.margin);
            const ahead = row.margin > 0 ? row.seedsAhead : row.seedsBehind;
            return (
              <li key={row.caseId}>
                <button type="button" className={styles.h2hRow} onClick={() => onSelect(row.caseId)}>
                  <span className={styles.h2hCase}>
                    <span className={styles.h2hCaseName}>{caseInfo(row.caseId)?.title ?? row.caseId}</span>
                    <TierBadge tier={row.tier} />
                  </span>
                  <span className={styles.h2hBarTrack} aria-hidden>
                    <span className={styles.h2hBar} style={{ width: `${(margin / scale) * 100}%` }} />
                  </span>
                  <span className={`${styles.h2hMargin} num`}>+{formatWhole(margin)}</span>
                  <span className={`${styles.h2hSeeds} num`} title={`Ahead on ${ahead} of ${row.seeds} seeds`}>
                    {ahead}/{row.seeds}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

export function HeadToHead({ strategies, report, onSelect }: Props) {
  const [a, setA] = useState(strategies[0]);
  const [b, setB] = useState(strategies[1]);
  const result = headToHead(report.stats[a], report.stats[b]);
  const scale = Math.max(1, ...[...result.aWins, ...result.bWins].map((row) => Math.abs(row.margin)));
  const picker = (value: string, onChange: (name: string) => void, other: string, label: string) => (
    <label className={styles.h2hPick}>
      <span className="visually-hidden">{label}</span>
      <select className={ui.select} value={value} onChange={(event) => onChange(event.target.value)}>
        {strategies.map((name) => (
          <option key={name} value={name} disabled={name === other}>
            {name}
          </option>
        ))}
      </select>
    </label>
  );
  return (
    <div className={`${ui.panel} ${styles.h2h}`}>
      <div className={styles.h2hControls}>
        {picker(a, setA, b, "First strategy")}
        <span className={ui.muted}>vs</span>
        {picker(b, setB, a, "Second strategy")}
        <span className={`${ui.small} ${ui.muted} ${styles.h2hSummary}`}>
          Both ran on the same cases and seeds, so the differences are paired. Margins are mean PnL per day; x/y counts
          the seeds it was ahead on.
        </span>
      </div>
      <div className={styles.h2hGrid}>
        <Side winner={a} loser={b} rows={result.aWins} scale={scale} onSelect={(caseId) => onSelect(a, caseId)} />
        <Side winner={b} loser={a} rows={result.bWins} scale={scale} onSelect={(caseId) => onSelect(b, caseId)} />
      </div>
    </div>
  );
}
