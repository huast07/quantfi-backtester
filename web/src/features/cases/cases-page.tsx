"use client";

import { useState } from "react";

import { TierBadge, tierLabel } from "@/components/badges";
import ui from "@/components/ui.module.css";
import { catalog, groupByTier, namedSuite } from "@/lib/catalog";
import { formatPercent } from "@/lib/format";
import { eventWindowText, modifierParams } from "@/lib/modifiers";
import { TIERS, type CaseInfo, type Tier } from "@/py/types";

import styles from "./cases.module.css";
import { DayDownload } from "./day-download";

const TIER_TEXT: Record<Tier, string> = {
  observed: "What the three real days look like, recreated with fresh noise.",
  plausible: "Behaviour the real data leaves room for but does not show.",
  stress: "Rare, extreme events that test risk limits and recovery.",
};

const FAMILY_LABEL: Record<string, string> = {
  observed: "Observed days",
  dynamics: "Price dynamics",
  microstructure: "Market microstructure",
  structure: "Cross-product structure",
  options: "Options",
  stress: "Stress events",
};

const quickCases = new Set(namedSuite("quick").case_ids);

function matches(info: CaseInfo, query: string): boolean {
  if (!query) return true;
  const haystack = [info.title, info.id, info.summary, info.description, info.family, ...info.references]
    .join(" ")
    .toLowerCase();
  return query
    .toLowerCase()
    .split(/\s+/)
    .every((word) => haystack.includes(word));
}

function byFamily(cases: CaseInfo[]): Array<[string, CaseInfo[]]> {
  const families = [...new Set(cases.map((c) => c.family))];
  return families.map((family) => [family, cases.filter((c) => c.family === family)]);
}

function CaseCard({ info }: { info: CaseInfo }) {
  return (
    <details className={`${ui.panel} ${styles.case}`} id={info.id}>
      <summary className={styles.caseSummary}>
        <span className={styles.caseTitle}>
          {info.title}
          {quickCases.has(info.id) && <span className={ui.chip}>Quick suite</span>}
        </span>
        <span className={`${ui.small} ${ui.muted}`}>{info.summary}</span>
      </summary>
      <div className={styles.caseBody}>
        <p>{info.description}</p>
        <dl className={styles.caseFacts}>
          <div>
            <dt>Case id</dt>
            <dd>
              <code>{info.id}</code>
            </dd>
          </div>
          <div>
            <dt>Event window</dt>
            <dd>{eventWindowText(info.event_window)}</dd>
          </div>
        </dl>
        {info.modifiers.length > 0 && (
          <div>
            <h4 className={styles.subTitle}>Changes to the calibrated day</h4>
            <ul className={styles.modifiers}>
              {info.modifiers.map((modifier, index) => (
                <li key={index}>
                  <span className={styles.modifierKind}>{modifier.kind}</span>
                  <span className={styles.params}>
                    {modifierParams(modifier).map(([name, value]) => (
                      <span key={name} className={styles.param}>
                        <span className={ui.faint}>{name}</span> {value}
                      </span>
                    ))}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {info.references.length > 0 && (
          <div>
            <h4 className={styles.subTitle}>Literature</h4>
            <ul className={styles.references}>
              {info.references.map((reference) => (
                <li key={reference}>{reference}</li>
              ))}
            </ul>
          </div>
        )}
        <DayDownload caseId={info.id} />
      </div>
    </details>
  );
}

export function CasesPage() {
  const [query, setQuery] = useState("");
  const [tier, setTier] = useState<Tier | "all">("all");
  const shown = catalog.cases.filter((c) => (tier === "all" || c.tier === tier) && matches(c, query.trim()));
  const count = (t: Tier) => catalog.cases.filter((c) => c.tier === t).length;

  return (
    <div className={ui.container}>
      <div className={ui.pageHeader}>
        <h1>Case library</h1>
        <p>
          Every backtest runs your strategies on these {catalog.cases.length} synthetic day-1 markets. Each case starts
          from a day calibrated to the real round 1 data and changes one thing, drawn from the market microstructure and
          trading literature.
        </p>
      </div>

      <div className={styles.tiers}>
        {TIERS.map((t) => (
          <div key={t} className={styles.tier}>
            <div className={styles.tierHead}>
              <TierBadge tier={t} />
              <span className={`${ui.small} ${ui.muted}`}>
                <span className="num">{count(t)}</span> cases, weight{" "}
                <span className="num">{formatPercent(catalog.tier_weights[t])}</span>
              </span>
            </div>
            <p className={`${ui.small} ${ui.muted}`}>{TIER_TEXT[t]}</p>
          </div>
        ))}
      </div>

      <div className={styles.toolbar}>
        <div className={styles.filters} role="group" aria-label="Tier">
          {(["all", ...TIERS] as const).map((t) => (
            <button
              key={t}
              type="button"
              className={`${styles.filter} ${tier === t ? styles.filterActive : ""}`}
              aria-pressed={tier === t}
              onClick={() => setTier(t)}
            >
              {t === "all" ? "All" : tierLabel(t)}
            </button>
          ))}
        </div>
        <input
          type="search"
          className={`${ui.input} ${styles.search}`}
          placeholder="Search cases, products or authors"
          aria-label="Search cases"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>

      {shown.length === 0 ? (
        <p className={ui.empty}>No case matches that search.</p>
      ) : (
        groupByTier(shown, (c) => c.tier).map((group) => (
          <section key={group.tier} className={styles.group}>
            <h2 className={styles.groupTitle}>
              {tierLabel(group.tier)} <span className={ui.faint}>{group.items.length}</span>
            </h2>
            {byFamily(group.items).map(([family, cases]) => (
              <div key={family} className={styles.family}>
                {group.items.length !== cases.length && (
                  <h3 className={styles.familyTitle}>{FAMILY_LABEL[family] ?? family}</h3>
                )}
                <div className={styles.cases}>
                  {cases.map((info) => (
                    <CaseCard key={info.id} info={info} />
                  ))}
                </div>
              </div>
            ))}
          </section>
        ))
      )}
    </div>
  );
}
