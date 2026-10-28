"use client";

import { useId, useState, type DragEvent } from "react";

import ui from "@/components/ui.module.css";
import {
  MAX_FILE_BYTES,
  MAX_STRATEGIES,
  type IncomingFile,
  type Rejection,
  type StrategyEntry,
} from "@/lib/strategy-files";

import styles from "./backtest.module.css";

interface Props {
  files: StrategyEntry[];
  rejected: Rejection[];
  disabled: boolean;
  onAdd: (files: IncomingFile[]) => void;
  onRemove: (name: string) => void;
}

async function readFiles(list: FileList | null): Promise<IncomingFile[]> {
  return Promise.all(
    Array.from(list ?? []).map(async (file) => ({
      name: file.name,
      size: file.size,
      source: file.size <= MAX_FILE_BYTES ? await file.text() : "",
    })),
  );
}

function formatBytes(bytes: number): string {
  return bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(1)} KB`;
}

function CheckStatus({ entry }: { entry: StrategyEntry }) {
  switch (entry.check.state) {
    case "checking":
      return <span className={`${styles.status} ${styles.statusChecking}`}>Checking</span>;
    case "ok":
      return <span className={`${styles.status} ${styles.statusOk}`}>Ready</span>;
    case "error":
      return <span className={`${styles.status} ${styles.statusError}`}>Needs a fix</span>;
  }
}

export function UploadPanel({ files, rejected, disabled, onAdd, onRemove }: Props) {
  const inputId = useId();
  const [dragging, setDragging] = useState(false);

  const onDrop = async (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault();
    setDragging(false);
    if (!disabled) onAdd(await readFiles(event.dataTransfer.files));
  };

  return (
    <section className={ui.panel} aria-labelledby={`${inputId}-title`}>
      <div className={ui.panelHeader}>
        <h2 id={`${inputId}-title`}>
          <span className={styles.step}>1</span> Strategies
        </h2>
        <span className={`${ui.small} ${ui.faint}`}>
          {files.length} of {MAX_STRATEGIES}
        </span>
      </div>
      <div className={ui.panelBody}>
        <label
          htmlFor={inputId}
          className={`${styles.dropzone} ${dragging ? styles.dragging : ""} ${disabled ? styles.dropzoneDisabled : ""}`}
          onDragOver={(event) => {
            event.preventDefault();
            if (!disabled) setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
        >
          <span className={styles.dropTitle}>Drop trader .py files here, or click to choose</span>
          <span className={`${ui.small} ${ui.muted}`}>
            Each file is a separate strategy with a <code>Trader</code> class, as submitted to the competition.{" "}
            <code>from datamodel import ...</code> works as usual.
          </span>
          <input
            id={inputId}
            type="file"
            accept=".py,text/x-python"
            multiple
            disabled={disabled}
            className="visually-hidden"
            onChange={async (event) => {
              const input = event.currentTarget;
              onAdd(await readFiles(input.files));
              input.value = "";
            }}
          />
        </label>

        {rejected.length > 0 && (
          <div className={`${ui.notice} ${ui.error} ${styles.rejections}`} role="alert">
            {rejected.map((r) => (
              <div key={`${r.name}-${r.reason}`}>
                <strong>{r.name}</strong> {r.reason}.
              </div>
            ))}
          </div>
        )}

        {files.length > 0 && (
          <ul className={styles.fileList}>
            {files.map((entry) => (
              <li key={entry.name} className={styles.file}>
                <div className={styles.fileMain}>
                  <span className={styles.fileName}>{entry.name}</span>
                  <span className={`${ui.small} ${ui.faint} num`}>{formatBytes(new Blob([entry.source]).size)}</span>
                  <CheckStatus entry={entry} />
                  <button
                    type="button"
                    className={`${ui.button} ${ui.ghost} ${ui.buttonSmall} ${styles.remove}`}
                    onClick={() => onRemove(entry.name)}
                    disabled={disabled}
                    aria-label={`Remove ${entry.name}`}
                  >
                    Remove
                  </button>
                </div>
                {entry.check.state === "error" && <pre className={styles.fileError}>{entry.check.message}</pre>}
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
