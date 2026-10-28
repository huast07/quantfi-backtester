import type { Rating, Tier } from "@/py/types";

import styles from "./badges.module.css";

const TIER_LABEL: Record<Tier, string> = { observed: "Observed", plausible: "Plausible", stress: "Stress" };
const RATING_LABEL: Record<Rating, string> = { strong: "Strong", neutral: "Neutral", weak: "Weak" };

export function TierBadge({ tier }: { tier: Tier }) {
  return <span className={`${styles.tier} ${styles[tier]}`}>{TIER_LABEL[tier]}</span>;
}

export function RatingBadge({ rating }: { rating: Rating }) {
  return <span className={`${styles.rating} ${styles[rating]}`}>{RATING_LABEL[rating]}</span>;
}

export const tierLabel = (tier: Tier) => TIER_LABEL[tier];
export const ratingLabel = (rating: Rating) => RATING_LABEL[rating];
