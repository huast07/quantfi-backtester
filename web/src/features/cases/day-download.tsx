"use client";

import { useId, useState } from "react";

import ui from "@/components/ui.module.css";
import { downloadCaseDay } from "@/lib/case-day";

import styles from "./cases.module.css";

const MAX_SEED = 9999;

export function DayDownload({ caseId }: { caseId: string }) {
  const id = useId();
  const [seed, setSeed] = useState("1");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const value = Number(seed);
  const valid = Number.isInteger(value) && value >= 1 && value <= MAX_SEED;

  const download = async () => {
    setBusy(true);
    setError(null);
    try {
      await downloadCaseDay(caseId, value);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={styles.download}>
      <label htmlFor={id} className={`${ui.small} ${ui.muted}`}>
        Seed
      </label>
      <input
        id={id}
        className={`${ui.input} ${styles.seedInput}`}
        type="number"
        inputMode="numeric"
        min={1}
        max={MAX_SEED}
        value={seed}
        onChange={(event) => setSeed(event.target.value)}
        aria-invalid={!valid}
      />
      <button type="button" className={`${ui.button} ${ui.buttonSmall}`} disabled={!valid || busy} onClick={download}>
        {busy ? "Generating..." : "Download day CSVs"}
      </button>
      {!valid && <span className={`${ui.small} ${styles.error}`}>Seeds run from 1 to {MAX_SEED}.</span>}
      {error && (
        <span className={`${ui.small} ${styles.error}`} role="alert">
          {error}
        </span>
      )}
    </div>
  );
}
