"use client";

import { useState } from "react";

import { RatingBadge, TierBadge } from "@/components/badges";
import ui from "@/components/ui.module.css";
import { caseInfo } from "@/lib/catalog";
import { formatPnl } from "@/lib/format";
import { overallScore, profile, type ProfileEntry } from "@/lib/scoring";
import type { CaseInfo, Report, TierWeights } from "@/py/types";

import styles from "./results.module.css";

const COLLAPSED = 4;

interface Props {
  strategies: string[];
  report: Report;
  cases: CaseInfo[];
  weights: TierWeights;
  onSelect: (strategy: string, caseId: string) => void;
}

function VerdictList({
  title,
  entries,
  empty,
  onSelect,
}: {
  title: string;
  entries: ProfileEntry[];
  empty: string;
  onSelect: (caseId: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const shown = open ? entries : entries.slice(0, COLLAPSED);
  return (
    <div className={styles.verdictList}>
      <h4 className={styles.listTitle}>
        {title} <span className={ui.faint}>{entries.length}</span>
      </h4>
      {entries.length === 0 ? (
        <p className={`${ui.small} ${ui.faint}`}>{empty}</p>
      ) : (
        <ul>
          {shown.map((entry) => (
            <li key={entry.verdict.case_id}>
              <button type="button" className={styles.verdictRow} onClick={() => onSelect(entry.verdict.case_id)}>
                <span className={styles.verdictHead}>
                  <span className={styles.verdictCase}>{entry.title}</span>
                  <TierBadge tier={entry.tier} />
                  <span className={`${styles.verdictPnl} num`}>{formatPnl(entry.stats.mean_pnl)}</span>
                </span>
                <span className={styles.verdictReason}>{entry.verdict.reason}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {entries.length > COLLAPSED && (
        <button type="button" className={styles.more} onClick={() => setOpen(!open)}>
          {open ? "Show fewer" : `Show all ${entries.length}`}
        </button>
      )}
    </div>
  );
}

export function ProfileCards({ strategies, report, cases, weights, onSelect }: Props) {
  return (
    <div className={styles.profiles}>
      {strategies.map((name) => {
        const stats = report.stats[name];
        const result = profile(report.verdicts[name], stats, cases);
        const score = overallScore(stats, weights);
        const crashes = stats.reduce((sum, s) => sum + s.errors.length, 0);
        const total = result.counts.strong + result.counts.neutral + result.counts.weak;
        return (
          <article key={name} className={`${ui.panel} ${styles.profile}`}>
            <header className={styles.profileHead}>
              <h3 className={styles.strategyName}>{name}</h3>
              <div className={styles.score}>
                <span className={`${styles.scoreValue} num`}>{formatPnl(score.weighted_pnl)}</span>
                <span className={`${ui.small} ${ui.muted}`}>weighted mean PnL per day</span>
              </div>
              <dl className={styles.facts}>
                <div>
                  <dt>Worst case</dt>
                  <dd>
                    {caseInfo(score.worst_case)?.title ?? score.worst_case}{" "}
                    <span className="num">{formatPnl(score.worst_case_pnl)}</span>
                  </dd>
                </div>
                <div>
                  <dt>Products traded</dt>
                  <dd className="num">{result.productsTraded}</dd>
                </div>
              </dl>
              <div className={styles.ratingBar} aria-label="Verdicts across cases">
                {(["strong", "neutral", "weak"] as const).map((rating) =>
                  result.counts[rating] > 0 ? (
                    <span
                      key={rating}
                      className={styles[`bar_${rating}`]}
                      style={{ flexGrow: result.counts[rating] }}
                      title={`${result.counts[rating]} ${rating}`}
                    />
                  ) : null,
                )}
              </div>
              <div className={styles.ratingCounts}>
                <RatingBadge rating="strong" /> <span className="num">{result.counts.strong}</span>
                <RatingBadge rating="neutral" /> <span className="num">{result.counts.neutral}</span>
                <RatingBadge rating="weak" /> <span className="num">{result.counts.weak}</span>
                <span className={ui.faint}>of {total} cases</span>
              </div>
              {crashes > 0 && (
                <p className={`${ui.notice} ${ui.error} ${styles.crashes}`}>
                  Crashed on {crashes} {crashes === 1 ? "day" : "days"}; those count as zero PnL. Open a weak case to
                  see the error.
                </p>
              )}
            </header>
            <VerdictList
              title="Performs well in"
              entries={result.strong}
              empty="No case stands out as strong."
              onSelect={(caseId) => onSelect(name, caseId)}
            />
            <VerdictList
              title="Performs poorly in"
              entries={result.weak}
              empty="No case stands out as weak."
              onSelect={(caseId) => onSelect(name, caseId)}
            />
          </article>
        );
      })}
    </div>
  );
}
