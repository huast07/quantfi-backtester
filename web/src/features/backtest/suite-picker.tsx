"use client";

import { useId } from "react";

import { tierLabel } from "@/components/badges";
import ui from "@/components/ui.module.css";
import { catalog, groupByTier, namedSuite, type SuiteName } from "@/lib/catalog";
import type { MatchMode } from "@/py/types";

import styles from "./backtest.module.css";

export type SuiteChoice = SuiteName | "custom";

export const MAX_CUSTOM_SEEDS = 10;

const SUITE_TEXT: Record<SuiteChoice, { title: string; note: string }> = {
  quick: { title: "Quick", note: "For fast iteration. One seed, so verdicts are only indicative." },
  standard: { title: "Standard", note: "Every case on two seeds. The default for comparing strategies." },
  full: { title: "Full", note: "Every case on five seeds. Use it before submitting." },
  custom: { title: "Custom", note: "Pick the cases and the number of seeds." },
};

const MATCH_TEXT: Record<MatchMode, { title: string; note: string }> = {
  all: {
    title: "All",
    note: "Market trades fill your resting orders at prices equal to or better than yours. This is the QuantiFi wiki rule.",
  },
  worse: { title: "Worse", note: "Only market trades strictly through your price fill you. A conservative check." },
  none: { title: "None", note: "Only the order book fills you; market trades never do." },
};

function suiteSize(choice: SuiteChoice, customCases: string[], customSeeds: number): string {
  if (choice === "custom") return `${customCases.length} cases × ${customSeeds} seed${customSeeds === 1 ? "" : "s"}`;
  const suite = namedSuite(choice);
  return `${suite.case_ids.length} cases × ${suite.seeds.length} seed${suite.seeds.length === 1 ? "" : "s"}`;
}

interface Props {
  choice: SuiteChoice;
  customCases: string[];
  customSeeds: number;
  matchMode: MatchMode;
  disabled: boolean;
  onChoice: (choice: SuiteChoice) => void;
  onCustomCases: (ids: string[]) => void;
  onCustomSeeds: (seeds: number) => void;
  onMatchMode: (mode: MatchMode) => void;
}

function CustomCases({
  selected,
  disabled,
  onChange,
}: {
  selected: string[];
  disabled: boolean;
  onChange: (ids: string[]) => void;
}) {
  const chosen = new Set(selected);
  const toggle = (ids: string[], on: boolean) =>
    onChange(catalog.cases.map((c) => c.id).filter((id) => (ids.includes(id) ? on : chosen.has(id))));
  return (
    <div className={styles.customCases}>
      {groupByTier(catalog.cases, (c) => c.tier).map(({ tier, items }) => {
        const ids = items.map((c) => c.id);
        const all = ids.every((id) => chosen.has(id));
        return (
          <fieldset key={tier} className={styles.tierColumn} disabled={disabled}>
            <legend className={styles.tierLegend}>
              <span>
                {tierLabel(tier)} <span className={ui.faint}>{items.length}</span>
              </span>
              <button type="button" className={styles.linkButton} onClick={() => toggle(ids, !all)}>
                {all ? "None" : "All"}
              </button>
            </legend>
            {items.map((c) => (
              <label key={c.id} className={styles.caseOption} title={c.summary}>
                <input
                  type="checkbox"
                  checked={chosen.has(c.id)}
                  onChange={(event) => toggle([c.id], event.target.checked)}
                />
                <span>{c.title}</span>
              </label>
            ))}
          </fieldset>
        );
      })}
    </div>
  );
}

export function SuitePicker(props: Props) {
  const { choice, customCases, customSeeds, matchMode, disabled } = props;
  const id = useId();
  return (
    <section className={ui.panel} aria-labelledby={`${id}-title`}>
      <div className={ui.panelHeader}>
        <h2 id={`${id}-title`}>
          <span className={styles.step}>2</span> Cases and matching
        </h2>
      </div>
      <div className={ui.panelBody}>
        <fieldset className={styles.fieldset} disabled={disabled}>
          <legend className={ui.label}>Suite</legend>
          <div className={styles.suiteGrid}>
            {(Object.keys(SUITE_TEXT) as SuiteChoice[]).map((option) => (
              <label key={option} className={`${styles.option} ${choice === option ? styles.optionChecked : ""}`}>
                <input
                  type="radio"
                  name={`${id}-suite`}
                  value={option}
                  checked={choice === option}
                  onChange={() => props.onChoice(option)}
                  className="visually-hidden"
                />
                <span className={styles.optionTitle}>
                  {SUITE_TEXT[option].title}
                  <span className={styles.optionSize}>{suiteSize(option, customCases, customSeeds)}</span>
                </span>
                <span className={styles.optionNote}>{SUITE_TEXT[option].note}</span>
              </label>
            ))}
          </div>
        </fieldset>

        {choice === "custom" && (
          <div className={styles.custom}>
            <CustomCases selected={customCases} disabled={disabled} onChange={props.onCustomCases} />
            <label className={styles.seedField}>
              <span className={ui.label}>Seeds per case</span>
              <input
                type="number"
                className={`${ui.input} num`}
                min={1}
                max={MAX_CUSTOM_SEEDS}
                value={customSeeds}
                disabled={disabled}
                onChange={(event) => {
                  const value = Math.round(Number(event.target.value));
                  if (Number.isFinite(value)) props.onCustomSeeds(Math.min(Math.max(value, 1), MAX_CUSTOM_SEEDS));
                }}
              />
            </label>
          </div>
        )}

        <fieldset className={`${styles.fieldset} ${styles.matchFieldset}`} disabled={disabled}>
          <legend className={ui.label}>Fills from market trades</legend>
          <div className={styles.segmented} role="radiogroup">
            {(Object.keys(MATCH_TEXT) as MatchMode[]).map((mode) => (
              <label key={mode} className={`${styles.segment} ${matchMode === mode ? styles.segmentChecked : ""}`}>
                <input
                  type="radio"
                  name={`${id}-match`}
                  value={mode}
                  checked={matchMode === mode}
                  onChange={() => props.onMatchMode(mode)}
                  className="visually-hidden"
                />
                {MATCH_TEXT[mode].title}
              </label>
            ))}
          </div>
          <p className={`${ui.small} ${ui.muted} ${styles.matchNote}`}>{MATCH_TEXT[matchMode].note}</p>
        </fieldset>
      </div>
    </section>
  );
}
