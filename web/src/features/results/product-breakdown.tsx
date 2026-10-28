"use client";

import { useState } from "react";

import { tierLabel } from "@/components/badges";
import ui from "@/components/ui.module.css";
import { caseInfo, groupByTier } from "@/lib/catalog";
import { formatPnl } from "@/lib/format";
import { productBreakdown } from "@/lib/scoring";
import type { Report } from "@/py/types";

import styles from "./results.module.css";

interface Props {
  strategies: string[];
  report: Report;
  productCount: number;
}

/** Background tint scaled by size, so the products that drive a result stand out. */
function tint(value: number, scale: number): string | undefined {
  if (value === 0 || scale === 0) return undefined;
  const strength = Math.round(Math.min(Math.abs(value) / scale, 1) * 45 + 8);
  return `color-mix(in srgb, var(${value > 0 ? "--strong" : "--weak"}) ${strength}%, transparent)`;
}

export function ProductBreakdown({ strategies, report, productCount }: Props) {
  const [name, setName] = useState(strategies[0]);
  const breakdown = productBreakdown(report.stats[name]);
  const products = breakdown.products.filter((p) => breakdown.rows.some((row) => row.pnl[p] !== 0));
  const scale = Math.max(0, ...breakdown.rows.flatMap((row) => products.map((p) => Math.abs(row.pnl[p]))));
  return (
    <div className={`${ui.panel} ${styles.products}`}>
      <div className={styles.productsHead}>
        <label>
          <span className="visually-hidden">Strategy</span>
          <select className={ui.select} value={name} onChange={(event) => setName(event.target.value)}>
            {strategies.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <span className={`${ui.small} ${ui.muted}`}>
          Breadth: made or lost money on <strong className="num">{breakdown.breadth}</strong> of {productCount}{" "}
          products. Cells are mean PnL per day.
        </span>
      </div>
      {products.length === 0 ? (
        <p className={ui.empty}>This strategy did not trade.</p>
      ) : (
        <div className={styles.tableScroll}>
          <table className={styles.productTable}>
            <thead>
              <tr>
                <th scope="col" className={styles.caseColumn}>
                  Case
                </th>
                {products.map((p) => (
                  <th key={p} scope="col" className={styles.productColumn}>
                    {p}
                  </th>
                ))}
              </tr>
            </thead>
            {groupByTier(breakdown.rows, (row) => row.tier).map(({ tier, items }) => (
              <tbody key={tier}>
                <tr className={styles.groupRow}>
                  <th scope="colgroup" colSpan={products.length + 1}>
                    {tierLabel(tier)}
                  </th>
                </tr>
                {items.map((row) => (
                  <tr key={row.caseId}>
                    <th scope="row" className={styles.caseColumn}>
                      {caseInfo(row.caseId)?.title ?? row.caseId}
                    </th>
                    {products.map((p) => (
                      <td
                        key={p}
                        className={`${styles.productCell} num`}
                        style={{ background: tint(row.pnl[p], scale) }}
                      >
                        {row.pnl[p] === 0 ? "" : formatPnl(row.pnl[p])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            ))}
            <tfoot>
              <tr>
                <th scope="row" className={styles.caseColumn}>
                  Mean over cases
                </th>
                {products.map((p) => (
                  <td key={p} className={`${styles.productCell} ${styles.footCell} num`}>
                    {formatPnl(breakdown.mean[p])}
                  </td>
                ))}
              </tr>
            </tfoot>
          </table>
        </div>
      )}
    </div>
  );
}
