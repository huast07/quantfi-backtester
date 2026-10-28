"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import ui from "@/components/ui.module.css";
import { caseInfo, catalog } from "@/lib/catalog";
import { downloadText } from "@/lib/download";
import { formatDateTime, formatDuration } from "@/lib/format";
import { exportRuns, openHistory, type SavedRun } from "@/lib/history";
import { overallScore } from "@/lib/scoring";
import { TIERS, type CaseInfo, type TierWeights } from "@/py/types";

import { CaseMatrix } from "./case-matrix";
import { DrillDown } from "./drill-down";
import { HeadToHead } from "./head-to-head";
import { ProductBreakdown } from "./product-breakdown";
import { ProfileCards } from "./profile-cards";
import styles from "./results.module.css";
import { WeightsControl } from "./weights-control";

type Loaded = { id: string; saved: SavedRun | null } | { id: string; error: string };

const MATCH_LABEL = { all: "all trades match", worse: "worse trades match", none: "no trade matching" } as const;

function useSavedRun(id: string): Loaded | null {
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  useEffect(() => {
    if (!id) return;
    let current = true;
    openHistory()
      .then((history) => history.get(id))
      .then(
        (saved) => current && setLoaded({ id, saved: saved ?? null }),
        (error: unknown) => current && setLoaded({ id, error: error instanceof Error ? error.message : String(error) }),
      );
    return () => {
      current = false;
    };
  }, [id]);
  return loaded?.id === id ? loaded : null;
}

export function ResultsPage() {
  const id = useSearchParams().get("id") ?? "";
  const loaded = useSavedRun(id);
  if (!id) return <Message title="No run selected">Open a run from History, or start a new backtest.</Message>;
  if (loaded === null) return <Message title="Loading results">Reading this run from your browser.</Message>;
  if ("error" in loaded) return <Message title="Could not open this run">{loaded.error}</Message>;
  if (loaded.saved === null) {
    return (
      <Message title="Run not found">
        Results live in the browser that ran them, and this one is not in this browser&apos;s history. It may have been
        deleted or run elsewhere; import its JSON export from History to view it here.
      </Message>
    );
  }
  return <Results key={loaded.saved.id} saved={loaded.saved} />;
}

function Message({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className={ui.container}>
      <div className={ui.pageHeader}>
        <h1>{title}</h1>
        <p>{children}</p>
      </div>
      <div className={ui.row}>
        <Link href="/" className={`${ui.button} ${ui.primary}`}>
          New backtest
        </Link>
        <Link href="/history" className={ui.button}>
          History
        </Link>
      </div>
    </div>
  );
}

function Section({ title, note, children }: { title: string; note?: string; children: React.ReactNode }) {
  return (
    <section>
      <div className={ui.sectionTitle}>
        <h2>{title}</h2>
        {note && <p>{note}</p>}
      </div>
      {children}
    </section>
  );
}

function Results({ saved }: { saved: SavedRun }) {
  const { report, plan } = saved;
  const strategies = plan.strategies.map((s) => s.name);
  const caseIds = plan.suite.case_ids;
  const cases = caseIds.map(caseInfo).filter((c): c is CaseInfo => c !== undefined);
  const firstStats = report.stats[strategies[0]];
  const tiersPresent = TIERS.filter((tier) => firstStats.some((s) => s.tier === tier));
  const productCount = Object.keys(firstStats[0]?.product_mean_pnl ?? {}).length;
  const [weights, setWeights] = useState<TierWeights>(catalog.tier_weights);
  const [selected, setSelected] = useState(() => ({
    strategy: strategies[0],
    caseId: overallScore(firstStats, catalog.tier_weights).worst_case,
  }));
  const drillRef = useRef<HTMLElement>(null);

  const select = (strategy: string, caseId: string) => {
    setSelected({ strategy, caseId });
    drillRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };
  const stamp = saved.createdAt.slice(0, 16).replace(/[:T]/g, "-");
  const seedCount = plan.suite.seeds.length;

  return (
    <div className={ui.container}>
      <div className={`${ui.pageHeader} ${styles.header}`}>
        <div>
          <h1>Results</h1>
          <p className={ui.meta}>
            <span>{formatDateTime(saved.createdAt)}</span>
            <span>
              {plan.suite.name} suite, {caseIds.length} cases x {seedCount} {seedCount === 1 ? "seed" : "seeds"}
            </span>
            <span>{MATCH_LABEL[plan.matchMode]}</span>
            <span>ran in {formatDuration(saved.durationMs)}</span>
          </p>
        </div>
        <div className={styles.actions}>
          <button
            type="button"
            className={`${ui.button} ${ui.buttonSmall}`}
            onClick={() => downloadText(`quantgen-run-${stamp}.json`, exportRuns([saved]), "application/json")}
          >
            Export JSON
          </button>
          <button
            type="button"
            className={`${ui.button} ${ui.buttonSmall}`}
            onClick={() => downloadText(`quantgen-report-${stamp}.txt`, report.text)}
          >
            Text report
          </button>
          <Link href="/" className={`${ui.button} ${ui.primary} ${ui.buttonSmall}`}>
            New run
          </Link>
        </div>
      </div>

      {report.indicative && (
        <p className={`${ui.notice} ${ui.warning}`}>
          This suite is small, so the verdicts are indicative. Run the Full suite before deciding what to submit.
        </p>
      )}

      <Section title="Profiles" note="The cases each strategy handles well or badly, and why.">
        <WeightsControl weights={weights} tiersPresent={tiersPresent} onChange={setWeights} />
        <ProfileCards strategies={strategies} report={report} cases={cases} weights={weights} onSelect={select} />
      </Section>

      <Section title="Strategy by case" note="Mean PnL per day. Pick a cell to replay it below.">
        <div className={ui.panel}>
          <CaseMatrix
            strategies={strategies}
            reference={catalog.reference}
            report={report}
            caseIds={caseIds}
            weights={weights}
            selected={selected}
            onSelect={select}
          />
        </div>
      </Section>

      {strategies.length > 1 && (
        <Section title="Head to head">
          <HeadToHead strategies={strategies} report={report} onSelect={select} />
        </Section>
      )}

      <Section title="Products" note="Which products drive each result.">
        <ProductBreakdown strategies={strategies} report={report} productCount={productCount} />
      </Section>

      <section ref={drillRef} className={styles.drillSection}>
        <div className={ui.sectionTitle}>
          <h2>Replay</h2>
          <p>Prices, fills, position, PnL and logs for one strategy on one simulated day.</p>
        </div>
        <DrillDown key={`${selected.strategy}|${selected.caseId}`} saved={saved} {...selected} />
      </section>
    </div>
  );
}
