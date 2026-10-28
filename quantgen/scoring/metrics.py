"""Per-run metrics and their aggregation per case and across a suite."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

import numpy as np

from quantgen.adapter.runner import DayResult
from quantgen.cases.case import TIERS

TIER_WEIGHTS: Mapping[str, float] = MappingProxyType({"observed": 0.6, "plausible": 0.3, "stress": 0.1})


@dataclass(frozen=True)
class RunMetrics:
    """One strategy on one case and seed. `error` is set (and the numbers are zero) when the strategy crashed."""

    strategy: str
    case_id: str
    seed: int
    total_pnl: float
    product_pnl: Mapping[str, float]
    max_drawdown: float
    own_trades: int
    limit_breaches: int
    error: str | None = None


def max_drawdown(pnl_path: Sequence[float]) -> float:
    if not pnl_path:
        return 0.0
    path = np.asarray(pnl_path, dtype=float)
    return float(np.max(np.maximum.accumulate(path) - path))


def run_metrics(strategy: str, case_id: str, seed: int, result: DayResult) -> RunMetrics:
    return RunMetrics(
        strategy=strategy,
        case_id=case_id,
        seed=seed,
        total_pnl=result.total_pnl,
        product_pnl=result.product_pnl,
        max_drawdown=max_drawdown(result.pnl_path),
        own_trades=result.own_trade_count,
        limit_breaches=result.limit_breaches,
    )


def failed_run(strategy: str, case_id: str, seed: int, error: str) -> RunMetrics:
    return RunMetrics(strategy, case_id, seed, 0.0, MappingProxyType({}), 0.0, 0, 0, error)


@dataclass(frozen=True)
class CaseStats:
    strategy: str
    case_id: str
    tier: str
    pnl_by_seed: Mapping[int, float]
    mean_pnl: float
    worst_pnl: float
    product_mean_pnl: Mapping[str, float]
    mean_drawdown: float
    limit_breaches: int
    errors: tuple[str, ...]

    @property
    def products_traded(self) -> int:
        return sum(1 for pnl in self.product_mean_pnl.values() if pnl != 0)


def case_stats(runs: Sequence[RunMetrics], tier: str) -> CaseStats:
    """Aggregate one strategy's runs on one case. Crashed runs count as zero PnL and are listed in `errors`."""
    first = runs[0]
    pnl = {run.seed: run.total_pnl for run in runs}
    products = sorted({name for run in runs for name in run.product_pnl})
    product_mean = {name: float(np.mean([run.product_pnl.get(name, 0.0) for run in runs])) for name in products}
    return CaseStats(
        strategy=first.strategy,
        case_id=first.case_id,
        tier=tier,
        pnl_by_seed=MappingProxyType(pnl),
        mean_pnl=float(np.mean(list(pnl.values()))),
        worst_pnl=float(min(pnl.values())),
        product_mean_pnl=MappingProxyType(product_mean),
        mean_drawdown=float(np.mean([run.max_drawdown for run in runs])),
        limit_breaches=sum(run.limit_breaches for run in runs),
        errors=tuple(f"seed {run.seed}: {run.error}" for run in runs if run.error),
    )


@dataclass(frozen=True)
class Overall:
    weighted_pnl: float
    worst_case: str
    worst_case_pnl: float


def tier_weighted(stats: Sequence[CaseStats], weights: Mapping[str, float] = TIER_WEIGHTS) -> float:
    """Each tier's weight is split equally among its cases, so adding cases never changes a tier's share. Tiers
    absent from the suite give their weight to the others in proportion."""
    present = {tier for tier in TIERS if any(s.tier == tier for s in stats)}
    total = sum(weights[tier] for tier in present)
    score = 0.0
    for tier in present:
        tier_stats = [s for s in stats if s.tier == tier]
        score += weights[tier] / total * float(np.mean([s.mean_pnl for s in tier_stats]))
    return score


def overall(stats: Sequence[CaseStats], weights: Mapping[str, float] = TIER_WEIGHTS) -> Overall:
    worst = min(stats, key=lambda s: s.mean_pnl)
    return Overall(tier_weighted(stats, weights), worst.case_id, worst.mean_pnl)
