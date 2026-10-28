// Mirrors of the JSON that quantgen/browser.py returns (dataclasses through quantgen.serde.to_dict).

export type Tier = "observed" | "plausible" | "stress";
export const TIERS: readonly Tier[] = ["observed", "plausible", "stress"];

export type MatchMode = "all" | "worse" | "none";
export type Rating = "strong" | "neutral" | "weak";
export type TierWeights = Record<Tier, number>;

export interface CaseInfo {
  id: string;
  title: string;
  tier: Tier;
  family: string;
  summary: string;
  description: string;
  references: string[];
  modifiers: Array<Record<string, unknown> & { kind: string }>;
  event_window: [number, number];
}

export interface SuiteInfo {
  case_ids: string[] | null;
  seeds: number[];
  indicative: boolean;
}

export interface Catalog {
  cases: CaseInfo[];
  suites: Record<string, SuiteInfo>;
  tier_weights: TierWeights;
  reference: string;
  match_modes: MatchMode[];
}

export interface StrategyFile {
  name: string;
  source: string;
}

export interface StrategyCheck {
  ok: boolean;
  error: string | null;
}

export interface RunMetrics {
  strategy: string;
  case_id: string;
  seed: number;
  total_pnl: number;
  product_pnl: Record<string, number>;
  max_drawdown: number;
  own_trades: number;
  limit_breaches: number;
  error: string | null;
}

export interface CaseStats {
  strategy: string;
  case_id: string;
  tier: Tier;
  pnl_by_seed: Record<string, number>;
  mean_pnl: number;
  worst_pnl: number;
  product_mean_pnl: Record<string, number>;
  mean_drawdown: number;
  limit_breaches: number;
  errors: string[];
}

export interface Verdict {
  strategy: string;
  case_id: string;
  rating: Rating;
  reason: string;
}

export interface Overall {
  weighted_pnl: number;
  worst_case: string;
  worst_case_pnl: number;
}

export interface Report {
  stats: Record<string, CaseStats[]>;
  verdicts: Record<string, Verdict[]>;
  overall: Record<string, Overall>;
  indicative: boolean;
  text: string;
}

export interface Fill {
  timestamp: number;
  price: number;
  quantity: number;
}

export interface ProductTrace {
  product: string;
  mid: number[];
  pnl: number[];
  position: number[];
  fills: Fill[];
}

export interface LogLine {
  timestamp: number;
  text: string;
}

export interface RunDetail {
  timestamps: number[];
  total_pnl: number[];
  product_pnl: Record<string, number>;
  products: ProductTrace[];
  logs: LogLine[];
  logs_truncated: boolean;
}

export interface CaseCsv {
  day: number;
  prices: string;
  trades: string;
}

export interface SuiteSpec {
  name: string;
  case_ids: string[];
  seeds: number[];
}

export interface RunCaseRequest {
  strategies: StrategyFile[];
  case_id: string;
  seed: number;
  match_mode: MatchMode;
  reference: boolean;
}

export interface StrategyRunRequest {
  strategy: StrategyFile;
  case_id: string;
  seed: number;
  match_mode: MatchMode;
}

export interface ReportRequest {
  suite: SuiteSpec;
  strategies: string[];
  runs: RunMetrics[];
}

/** Every function in quantgen/browser.py, with its payload and decoded result. */
export interface PythonApi {
  catalog: { payload: undefined; result: Catalog };
  check_strategy: { payload: StrategyFile; result: StrategyCheck };
  run_case: { payload: RunCaseRequest; result: RunMetrics[] };
  report: { payload: ReportRequest; result: Report };
  drill: { payload: StrategyRunRequest; result: RunDetail };
  visualizer_log: { payload: StrategyRunRequest; result: string };
  case_csv: { payload: { case_id: string; seed: number }; result: CaseCsv };
}

export type ApiMethod = keyof PythonApi;
