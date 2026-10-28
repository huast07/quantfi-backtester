"use client";

import { tierLabel } from "@/components/badges";
import { caseInfo, groupByTier } from "@/lib/catalog";
import { formatPnl } from "@/lib/format";
import { tierWeighted } from "@/lib/scoring";
import type { Report, TierWeights } from "@/py/types";

import styles from "./results.module.css";

interface Props {
  strategies: string[];
  reference: string;
  report: Report;
  caseIds: string[];
  weights: TierWeights;
  selected: { strategy: string; caseId: string } | null;
  onSelect: (strategy: string, caseId: string) => void;
}

export function CaseMatrix({ strategies, reference, report, caseIds, weights, selected, onSelect }: Props) {
  const columns = [...strategies, ...(reference in report.stats ? [reference] : [])];
  const index = new Map(caseIds.map((id, i) => [id, i]));
  const groups = groupByTier(caseIds, (id) => report.stats[columns[0]][index.get(id) as number].tier);
  return (
    <div className={styles.tableScroll}>
      <table className={styles.matrix}>
        <thead>
          <tr>
            <th scope="col" className={styles.caseColumn}>
              Case
            </th>
            {columns.map((name) => (
              <th
                key={name}
                scope="col"
                className={`${styles.numColumn} ${name === reference ? styles.referenceColumn : ""}`}
              >
                <span className={styles.columnName} title={name}>
                  {name}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        {groups.map(({ tier, items }) => (
          <tbody key={tier}>
            <tr className={styles.groupRow}>
              <th scope="colgroup" colSpan={columns.length + 1}>
                {tierLabel(tier)} <span className={styles.groupCount}>{items.length}</span>
              </th>
            </tr>
            {items.map((caseId) => {
              const i = index.get(caseId) as number;
              return (
                <tr key={caseId}>
                  <th scope="row" className={styles.caseColumn}>
                    <span title={caseInfo(caseId)?.summary}>{caseInfo(caseId)?.title ?? caseId}</span>
                  </th>
                  {columns.map((name) => {
                    const stats = report.stats[name][i];
                    const verdict = report.verdicts[name]?.[i];
                    const isSelected = selected?.strategy === name && selected.caseId === caseId;
                    const label = `${name} on ${caseInfo(caseId)?.title ?? caseId}: ${formatPnl(stats.mean_pnl)}${
                      verdict ? `, ${verdict.rating}` : ""
                    }`;
                    return (
                      <td key={name} className={styles.numColumn}>
                        <button
                          type="button"
                          className={`${styles.cell} ${verdict ? styles[`cell_${verdict.rating}`] : styles.cellReference} ${
                            isSelected ? styles.cellSelected : ""
                          }`}
                          onClick={() => onSelect(name, caseId)}
                          title={verdict?.reason ?? "Reference strategy (a gate for verdicts, not rated)"}
                          aria-label={label}
                          aria-pressed={isSelected}
                        >
                          <span className="num">{formatPnl(stats.mean_pnl)}</span>
                          {stats.errors.length > 0 && <span className={styles.crashMark}>!</span>}
                        </button>
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        ))}
        <tfoot>
          <tr>
            <th scope="row" className={styles.caseColumn}>
              Weighted score
            </th>
            {columns.map((name) => (
              <td key={name} className={`${styles.numColumn} ${styles.footCell} num`}>
                {formatPnl(tierWeighted(report.stats[name], weights))}
              </td>
            ))}
          </tr>
        </tfoot>
      </table>
    </div>
  );
}
