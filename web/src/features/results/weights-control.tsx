"use client";

import { tierLabel } from "@/components/badges";
import ui from "@/components/ui.module.css";
import { catalog } from "@/lib/catalog";
import { formatPercent } from "@/lib/format";
import { TIERS, type Tier, type TierWeights } from "@/py/types";

import styles from "./results.module.css";

interface Props {
  weights: TierWeights;
  tiersPresent: Tier[];
  onChange: (weights: TierWeights) => void;
}

const STEP = 5;

export function WeightsControl({ weights, tiersPresent, onChange }: Props) {
  const total = tiersPresent.reduce((sum, tier) => sum + weights[tier], 0);
  const isDefault = TIERS.every((tier) => weights[tier] === catalog.tier_weights[tier]);
  return (
    <div className={styles.weights}>
      <span className={styles.weightsLabel}>Tier weights</span>
      {TIERS.map((tier) => {
        const present = tiersPresent.includes(tier);
        const percent = Math.round(weights[tier] * 100);
        return (
          <label key={tier} className={`${styles.weight} ${present ? "" : styles.weightAbsent}`}>
            <span className={styles.weightName}>{tierLabel(tier)}</span>
            <input
              type="range"
              min={0}
              max={100}
              step={STEP}
              value={percent}
              disabled={!present}
              onChange={(event) => {
                const next = { ...weights, [tier]: Number(event.target.value) / 100 };
                // At least one tier in the suite must keep some weight.
                if (tiersPresent.some((t) => next[t] > 0)) onChange(next);
              }}
              aria-valuetext={present && total > 0 ? formatPercent(weights[tier] / total) : "not in this suite"}
            />
            <span className={`${styles.weightValue} num`}>
              {present && total > 0 ? formatPercent(weights[tier] / total) : "n/a"}
            </span>
          </label>
        );
      })}
      <button
        type="button"
        className={`${ui.button} ${ui.ghost} ${ui.buttonSmall}`}
        disabled={isDefault}
        onClick={() => onChange(catalog.tier_weights)}
      >
        Reset
      </button>
    </div>
  );
}
