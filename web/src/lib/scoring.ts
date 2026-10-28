// Client-side scoring views over a report: re-weighting tiers (mirrors quantgen/scoring/metrics.py), strategy
// profiles, head-to-head comparisons and per-product breakdowns. Pure functions of Python's CaseStats and Verdicts.
import {
  TIERS,
  type CaseInfo,
  type CaseStats,
  type Overall,
  type Rating,
  type Tier,
  type TierWeights,
  type Verdict,
} from "@/py/types";

const mean = (values: number[]): number => values.reduce((sum, value) => sum + value, 0) / values.length;

/** Each tier's weight is split equally among its cases; tiers absent from the suite give their weight to the rest. */
export function tierWeighted(stats: CaseStats[], weights: TierWeights): number {
  const present = TIERS.filter((tier) => stats.some((s) => s.tier === tier));
  const total = present.reduce((sum, tier) => sum + weights[tier], 0);
  if (!(total > 0)) {
    throw new RangeError("At least one tier in this suite needs a positive weight");
  }
  return present.reduce((score, tier) => {
    const tierMean = mean(stats.filter((s) => s.tier === tier).map((s) => s.mean_pnl));
    return score + (weights[tier] / total) * tierMean;
  }, 0);
}

export function overallScore(stats: CaseStats[], weights: TierWeights): Overall {
  const worst = stats.reduce((low, s) => (s.mean_pnl < low.mean_pnl ? s : low));
  return { weighted_pnl: tierWeighted(stats, weights), worst_case: worst.case_id, worst_case_pnl: worst.mean_pnl };
}

export interface ProfileEntry {
  verdict: Verdict;
  stats: CaseStats;
  tier: Tier;
  title: string;
}

export interface Profile {
  strong: ProfileEntry[];
  weak: ProfileEntry[];
  counts: Record<Rating, number>;
  productsTraded: number;
}

/** Products with non-zero mean PnL in the case where the strategy traded the most (as the CLI reports it). */
export function productsTraded(stats: CaseStats[]): number {
  return Math.max(0, ...stats.map((s) => Object.values(s.product_mean_pnl).filter((pnl) => pnl !== 0).length));
}

export function profile(verdicts: Verdict[], stats: CaseStats[], cases: CaseInfo[]): Profile {
  const byId = new Map(cases.map((c) => [c.id, c]));
  const entries = verdicts.map((verdict, index) => {
    const info = byId.get(verdict.case_id);
    return {
      verdict,
      stats: stats[index],
      tier: info?.tier ?? stats[index].tier,
      title: info?.title ?? verdict.case_id,
    };
  });
  const rated = (rating: Rating) => entries.filter((entry) => entry.verdict.rating === rating);
  return {
    strong: rated("strong").toSorted((a, b) => b.stats.mean_pnl - a.stats.mean_pnl),
    weak: rated("weak").toSorted((a, b) => a.stats.mean_pnl - b.stats.mean_pnl),
    counts: { strong: rated("strong").length, neutral: rated("neutral").length, weak: rated("weak").length },
    productsTraded: productsTraded(stats),
  };
}

export interface HeadToHeadRow {
  caseId: string;
  tier: Tier;
  /** A's mean PnL minus B's. */
  margin: number;
  seedsAhead: number;
  seedsBehind: number;
  seeds: number;
}

export interface HeadToHead {
  aWins: HeadToHeadRow[];
  bWins: HeadToHeadRow[];
  ties: HeadToHeadRow[];
}

/** `a` and `b` are two strategies' stats over the same cases, in the same order. */
export function headToHead(a: CaseStats[], b: CaseStats[]): HeadToHead {
  const rows = a.map((caseA, index): HeadToHeadRow => {
    const caseB = b[index];
    const seeds = Object.keys(caseA.pnl_by_seed);
    const diffs = seeds.map((seed) => caseA.pnl_by_seed[seed] - caseB.pnl_by_seed[seed]);
    return {
      caseId: caseA.case_id,
      tier: caseA.tier,
      margin: caseA.mean_pnl - caseB.mean_pnl,
      seedsAhead: diffs.filter((diff) => diff > 0).length,
      seedsBehind: diffs.filter((diff) => diff < 0).length,
      seeds: seeds.length,
    };
  });
  return {
    aWins: rows.filter((row) => row.margin > 0).toSorted((x, y) => y.margin - x.margin),
    bWins: rows.filter((row) => row.margin < 0).toSorted((x, y) => x.margin - y.margin),
    ties: rows.filter((row) => row.margin === 0),
  };
}

export interface ProductBreakdown {
  /** Every product with PnL in any case, best mean first. */
  products: string[];
  rows: Array<{ caseId: string; tier: Tier; pnl: Record<string, number> }>;
  mean: Record<string, number>;
  /** How many products the strategy made or lost money on in at least one case. */
  breadth: number;
}

export function productBreakdown(stats: CaseStats[]): ProductBreakdown {
  const names = [...new Set(stats.flatMap((s) => Object.keys(s.product_mean_pnl)))];
  const rows = stats.map((s) => ({
    caseId: s.case_id,
    tier: s.tier,
    pnl: Object.fromEntries(names.map((name) => [name, s.product_mean_pnl[name] ?? 0])),
  }));
  const meanPnl = Object.fromEntries(names.map((name) => [name, mean(rows.map((row) => row.pnl[name]))]));
  return {
    products: names.toSorted((x, y) => meanPnl[y] - meanPnl[x] || x.localeCompare(y)),
    rows,
    mean: meanPnl,
    breadth: names.filter((name) => rows.some((row) => row.pnl[name] !== 0)).length,
  };
}
