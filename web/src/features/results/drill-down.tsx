"use client";

import { useEffect, useMemo, useState } from "react";

import { TierBadge } from "@/components/badges";
import ui from "@/components/ui.module.css";
import { caseInfo } from "@/lib/catalog";
import { downloadCaseDay } from "@/lib/case-day";
import { downloadText } from "@/lib/download";
import { defaultProduct, drillSeries } from "@/lib/drill";
import { formatPnl, formatPrice, formatWhole } from "@/lib/format";
import type { SavedRun } from "@/lib/history";
import { pythonClient } from "@/py/client";
import type { RunDetail, StrategyRunRequest } from "@/py/types";
import { isAbortError } from "@/worker/pool";

import { Chart } from "./chart";
import styles from "./results.module.css";

interface Props {
  saved: SavedRun;
  strategy: string;
  caseId: string;
}

/** Log lines rendered at once; the filter narrows the rest down. */
const LOG_LIMIT = 400;
const SYNC_KEY = "drill";
const POSITION_HEIGHT = 160;

type Trace = { key: string; detail: RunDetail } | { key: string; error: string };

const fileStem = (name: string) => name.replace(/\.py$/, "");
const errorMessage = (error: unknown) => (error instanceof Error ? error.message : String(error));

function useTrace(request: StrategyRunRequest | null): Trace | null {
  const key = request ? `${request.strategy.name}|${request.case_id}|${request.seed}|${request.match_mode}` : "";
  const [trace, setTrace] = useState<Trace | null>(null);
  useEffect(() => {
    if (!request) return;
    const abort = new AbortController();
    pythonClient()
      .call("drill", request, { signal: abort.signal })
      .then(
        (detail) => setTrace({ key, detail }),
        (error: unknown) => {
          if (!isAbortError(error)) setTrace({ key, error: errorMessage(error) });
        },
      );
    return () => abort.abort();
    // The key captures everything the request depends on.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return trace?.key === key ? trace : null;
}

function Logs({ detail }: { detail: RunDetail }) {
  const [filter, setFilter] = useState("");
  const needle = filter.trim().toLowerCase();
  const matching = needle ? detail.logs.filter((line) => line.text.toLowerCase().includes(needle)) : detail.logs;
  return (
    <div className={styles.logs}>
      <div className={styles.logsHead}>
        <h4 className={styles.listTitle}>
          Trader logs <span className={ui.faint}>{formatWhole(detail.logs.length)} lines</span>
        </h4>
        {detail.logs.length > 0 && (
          <input
            type="search"
            className={`${ui.input} ${styles.logFilter}`}
            placeholder="Filter lines"
            aria-label="Filter log lines"
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
          />
        )}
      </div>
      {detail.logs_truncated && (
        <p className={`${ui.small} ${ui.muted}`}>
          The strategy printed more than the browser keeps; the visualizer log has every line.
        </p>
      )}
      {detail.logs.length === 0 ? (
        <p className={`${ui.small} ${ui.faint}`}>This strategy printed nothing on this day.</p>
      ) : (
        <pre className={styles.logBody} tabIndex={0} aria-label="Trader log lines">
          {matching.slice(0, LOG_LIMIT).map((line, index) => (
            <span key={index} className={styles.logLine}>
              <span className={styles.logTime}>{line.timestamp}</span>
              {line.text}
            </span>
          ))}
          {matching.length === 0 && <span className={styles.logLine}>No line matches.</span>}
          {matching.length > LOG_LIMIT && (
            <span className={`${styles.logLine} ${styles.logMore}`}>
              {formatWhole(matching.length - LOG_LIMIT)} more lines; filter to narrow them down.
            </span>
          )}
        </pre>
      )}
    </div>
  );
}

function Charts({ detail, stem }: { detail: RunDetail; stem: string }) {
  const [picked, setPicked] = useState<string | null>(null);
  const product = picked && detail.products.some((p) => p.product === picked) ? picked : defaultProduct(detail);
  const series = useMemo(() => (product ? drillSeries(detail, product) : null), [detail, product]);
  if (!product || !series) return <p className={ui.empty}>This strategy did not trade on this day.</p>;
  const name = `${stem}-${product}`;
  return (
    <>
      <div className={styles.drillControls}>
        <label className={styles.drillField}>
          <span className={ui.label}>Product</span>
          <select className={ui.select} value={product} onChange={(event) => setPicked(event.target.value)}>
            {detail.products.map((p) => (
              <option key={p.product} value={p.product}>
                {p.product} ({formatPnl(detail.product_pnl[p.product] ?? 0)})
              </option>
            ))}
          </select>
        </label>
        <p className={`${ui.small} ${ui.muted}`}>
          Bought <span className="num">{formatWhole(series.bought)}</span> and sold{" "}
          <span className="num">{formatWhole(series.sold)}</span> lots. Hover a chart to read all three at one tick.
        </p>
      </div>
      <div className={styles.charts}>
        <Chart
          title={`${product} mid price and fills`}
          exportName={`${name}-price`}
          series={[
            { label: "Mid", color: "--chart-1" },
            { label: "Bought", color: "--chart-buy", kind: "points", marker: "up" },
            { label: "Sold", color: "--chart-sell", kind: "points", marker: "down" },
          ]}
          data={series.price}
          formatValue={formatPrice}
          syncKey={SYNC_KEY}
        />
        <Chart
          title={`${product} position`}
          exportName={`${name}-position`}
          series={[{ label: "Position", color: "--chart-2", kind: "step" }]}
          data={series.position}
          height={POSITION_HEIGHT}
          formatValue={formatWhole}
          syncKey={SYNC_KEY}
        />
        <Chart
          title="Profit and loss"
          exportName={`${name}-pnl`}
          series={[
            { label: product, color: "--chart-1" },
            { label: "All products", color: "--chart-3" },
          ]}
          data={series.pnl}
          formatValue={formatPnl}
          syncKey={SYNC_KEY}
        />
      </div>
    </>
  );
}

function Downloads({ request, caseId, seed }: { request: StrategyRunRequest | null; caseId: string; seed: number }) {
  const [busy, setBusy] = useState<"log" | "csv" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const run = async (kind: "log" | "csv", task: () => Promise<void>) => {
    setBusy(kind);
    setError(null);
    try {
      await task();
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setBusy(null);
    }
  };
  const downloadLog = (req: StrategyRunRequest) =>
    run("log", async () => {
      const log = await pythonClient().call("visualizer_log", req);
      downloadText(`${fileStem(req.strategy.name)}-${caseId}-seed${seed}.log`, log);
    });
  const downloadCsv = () => run("csv", () => downloadCaseDay(caseId, seed));
  return (
    <div className={styles.downloads}>
      {request && (
        <button
          type="button"
          className={`${ui.button} ${ui.buttonSmall}`}
          disabled={busy !== null}
          onClick={() => downloadLog(request)}
          title="The full prosperity3bt log, for the open-source Prosperity visualizer"
        >
          {busy === "log" ? "Preparing log..." : "Download visualizer log"}
        </button>
      )}
      <button type="button" className={`${ui.button} ${ui.buttonSmall}`} disabled={busy !== null} onClick={downloadCsv}>
        {busy === "csv" ? "Preparing CSVs..." : "Download day CSVs"}
      </button>
      {error && (
        <span className={`${ui.small} ${styles.downloadError}`} role="alert">
          {error}
        </span>
      )}
    </div>
  );
}

export function DrillDown({ saved, strategy, caseId }: Props) {
  const seeds = saved.plan.suite.seeds;
  const [seed, setSeed] = useState(seeds[0]);
  const file = saved.plan.strategies.find((s) => s.name === strategy);
  const request = file ? { strategy: file, case_id: caseId, seed, match_mode: saved.plan.matchMode } : null;
  const trace = useTrace(request);
  const info = caseInfo(caseId);
  const stats = saved.report.stats[strategy]?.find((s) => s.case_id === caseId);
  const verdict = saved.report.verdicts[strategy]?.find((v) => v.case_id === caseId);
  const runError = saved.runs.find((r) => r.strategy === strategy && r.case_id === caseId && r.seed === seed)?.error;
  const stem = `${fileStem(strategy)}-${caseId}-seed${seed}`;

  return (
    <div className={`${ui.panel} ${styles.drill}`}>
      <header className={styles.drillHead}>
        <div className={styles.drillTitle}>
          <h3>
            <span className={styles.mono}>{strategy}</span> on {info?.title ?? caseId}
          </h3>
          {info && <TierBadge tier={info.tier} />}
        </div>
        {info && <p className={`${ui.small} ${ui.muted}`}>{info.summary}</p>}
        {verdict && <p className={ui.small}>{verdict.reason}</p>}
      </header>

      <div className={styles.seeds} role="group" aria-label="Seed">
        {seeds.map((s) => {
          const pnl = stats?.pnl_by_seed[String(s)];
          return (
            <button
              key={s}
              type="button"
              className={`${styles.seed} ${s === seed ? styles.seedActive : ""}`}
              aria-pressed={s === seed}
              onClick={() => setSeed(s)}
            >
              <span>Seed {s}</span>
              {pnl !== undefined && <span className="num">{formatPnl(pnl)}</span>}
            </button>
          );
        })}
      </div>

      <div className={styles.drillBody}>
        {runError && (
          <p className={`${ui.notice} ${ui.error}`} role="alert">
            Crashed on this day: {runError}
          </p>
        )}
        {!file ? (
          <p className={ui.notice}>
            The reference strategy is built into the backtester, so its traces are not shown here. Pick one of your
            files in the matrix to see its fills, position and logs.
          </p>
        ) : trace === null ? (
          <p className={ui.empty} aria-live="polite">
            Replaying seed {seed}...
          </p>
        ) : "error" in trace ? (
          <p className={`${ui.notice} ${ui.error}`} role="alert">
            Could not replay this day: {trace.error}
          </p>
        ) : (
          <>
            <Charts key={stem} detail={trace.detail} stem={stem} />
            <Logs key={`${strategy}-${stem}`} detail={trace.detail} />
          </>
        )}
        <Downloads request={request} caseId={caseId} seed={seed} />
      </div>
    </div>
  );
}
