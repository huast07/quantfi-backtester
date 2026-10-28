"""Fit the taker models (generator/takers.py) to the real trade tapes."""

from collections.abc import Sequence

import numpy as np

from quantgen.generator.takers import (
    BUY,
    SELL,
    ChaseFlow,
    IvRuleFlow,
    NoiseFlow,
    Orders,
    SizeDistribution,
    selective_intensity,
    ticks_since_jump,
)
from quantgen.market_day import ProductDay

DISPERSION_WINDOW = 100


def trade_sides(day: ProductDay) -> np.ndarray:
    """BUY when a print is at or above the same-tick best ask (the taker lifted the offer), else SELL."""
    return np.where(day.trade_prices >= day.ask_prices[day.trade_ticks, 0], BUY, SELL)


def size_distribution(sizes: np.ndarray) -> SizeDistribution:
    values, counts = np.unique(sizes, return_counts=True)
    return SizeDistribution(sizes=tuple(int(v) for v in values), probs=tuple(float(c) for c in counts / counts.sum()))


def cluster_mean(days: Sequence[ProductDay]) -> float:
    """Geometric cluster size implied by the dispersion of prints per window: var/mean = 2m - 1."""
    counts = np.concatenate(
        [np.bincount(day.trade_ticks // DISPERSION_WINDOW, minlength=day.ticks // DISPERSION_WINDOW) for day in days]
    )
    if counts.mean() == 0:
        return 1.0
    return max(1.0, (counts.var() / counts.mean() + 1.0) / 2.0)


def fit_noise_flow(days: Sequence[ProductDay]) -> NoiseFlow:
    ticks = sum(day.ticks for day in days)
    sides = np.concatenate([trade_sides(day) for day in days])
    return NoiseFlow(
        rate=sides.shape[0] / ticks,
        buy_prob=float(np.mean(sides == BUY)),
        size=size_distribution(np.concatenate([day.trade_quantities for day in days])),
        cluster_mean=cluster_mean(days),
    )


def rule_consistency(measured: float, agreement: float) -> float:
    """Undo sign noise in the measured mispricing.

    If the measured mispricing agrees in sign with the true one with probability q, a taker that follows the true
    sign with consistency c looks consistent c*q + (1-c)*(1-q) of the time.
    """
    if agreement <= 0.5:
        return 0.5
    return float(np.clip((measured - (1.0 - agreement)) / (2.0 * agreement - 1.0), 0.5, 1.0))


MAX_SELECTIVITY = 4.0
SELECTIVITY_TOLERANCE = 1e-3


def _selection_ratio(residuals: Sequence[np.ndarray], selectivity: float) -> float:
    """Expected mean |residual| at trades over the mean |residual|, for takers with this selectivity."""
    weighted = sum(float(np.sum(np.abs(r) * selective_intensity(r, selectivity))) for r in residuals)
    return weighted / sum(float(np.sum(np.abs(r))) for r in residuals)


def fit_selectivity(residuals: Sequence[np.ndarray], trade_ticks: Sequence[np.ndarray]) -> float:
    """The selectivity whose expected |residual| at trades matches the observed one (bisection, it is monotone)."""
    observed = sum(float(np.sum(np.abs(r[t]))) for r, t in zip(residuals, trade_ticks, strict=True))
    observed /= sum(t.shape[0] for t in trade_ticks)
    target = observed / (sum(float(np.sum(np.abs(r))) for r in residuals) / sum(r.shape[0] for r in residuals))
    low, high = 0.0, MAX_SELECTIVITY
    if _selection_ratio(residuals, low) >= target:
        return low
    if _selection_ratio(residuals, high) <= target:
        return high
    while high - low > SELECTIVITY_TOLERANCE:
        middle = (low + high) / 2
        low, high = (middle, high) if _selection_ratio(residuals, middle) < target else (low, middle)
    return (low + high) / 2


def fit_iv_rule_flow(days: Sequence[ProductDay], residuals: Sequence[np.ndarray], agreement: float) -> IvRuleFlow:
    """`residuals` are the measured mispricings (mid minus smile price) per tick, one array per day."""
    ticks = sum(day.ticks for day in days)
    follows = [
        np.where(residual[day.trade_ticks] < 0, BUY, SELL) == trade_sides(day)
        for day, residual in zip(days, residuals, strict=True)
    ]
    return IvRuleFlow(
        rate=sum(day.trade_ticks.shape[0] for day in days) / ticks,
        consistency=rule_consistency(float(np.mean(np.concatenate(follows))), agreement),
        size=size_distribution(np.concatenate([day.trade_quantities for day in days])),
        selectivity=fit_selectivity(residuals, [day.trade_ticks for day in days]),
    )


def taker_orders(day: ProductDay) -> Orders:
    """The real tape as taker orders, one per tick."""
    return Orders(*_orders(day))


def _orders(day: ProductDay) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Collapse prints into one order per tick (a sweep prints once per level, always on one side)."""
    ticks, first = np.unique(day.trade_ticks, return_index=True)
    sizes = np.bincount(day.trade_ticks, weights=day.trade_quantities, minlength=day.ticks)[ticks].astype(np.int64)
    return ticks, trade_sides(day)[first], sizes


class _ChaseTally:
    def __init__(self, bins: int) -> None:
        self.ticks = np.zeros(bins)
        self.orders = np.zeros(bins)
        self.with_jump = np.zeros(bins)
        self.spread = np.zeros(bins)
        self.volume = np.zeros(bins)
        self.base_ticks = 0
        self.base_orders = 0
        self.base_spreads: list[np.ndarray] = []
        self.base_volumes: list[np.ndarray] = []
        self.chase_sizes: list[np.ndarray] = []
        self.base_sizes: list[np.ndarray] = []

    def add(self, day: ProductDay, jump_ticks: np.ndarray, jump_signs: np.ndarray, bin_ticks: int) -> None:
        bins = self.ticks.shape[0]
        since, last = ticks_since_jump(day.ticks, jump_ticks)
        in_window = (since >= 0) & (since < bin_ticks * bins)
        order_ticks, sides, sizes = _orders(day)
        spread = day.ask_prices[:, 0] - day.bid_prices[:, 0]
        tick_bins = since[in_window] // bin_ticks
        self.ticks += np.bincount(tick_bins, minlength=bins)
        self.spread += np.bincount(tick_bins, weights=spread[in_window], minlength=bins)
        up = jump_signs[np.maximum(last, 0)] > 0 if len(jump_signs) else np.zeros(day.ticks, dtype=bool)
        chased_volume = np.where(up, day.ask_volumes[:, 0], day.bid_volumes[:, 0])
        self.volume += np.bincount(tick_bins, weights=chased_volume[in_window], minlength=bins)
        self.base_volumes.append(np.concatenate([day.bid_volumes[~in_window, 0], day.ask_volumes[~in_window, 0]]))

        chasing = in_window[order_ticks]
        order_bins = since[order_ticks[chasing]] // bin_ticks
        signs = jump_signs[last[order_ticks[chasing]]]
        self.orders += np.bincount(order_bins, minlength=bins)
        self.with_jump += np.bincount(order_bins, weights=(sides[chasing] == signs), minlength=bins)
        self.chase_sizes.append(sizes[chasing])
        self.base_sizes.append(sizes[~chasing])
        self.base_ticks += int((~in_window).sum())
        self.base_orders += int((~chasing).sum())
        self.base_spreads.append(spread[~in_window])


def fit_chase_flow(
    days: Sequence[ProductDay], jumps: Sequence[tuple[np.ndarray, np.ndarray]], bin_ticks: int, bins: int
) -> ChaseFlow:
    """`jumps` holds (jump ticks, jump signs) per day; a jump at tick j is the move from tick j-1 to tick j."""
    tally = _ChaseTally(bins)
    for day, (jump_ticks, jump_signs) in zip(days, jumps, strict=True):
        tally.add(day, jump_ticks, jump_signs, bin_ticks)
    base_spread = float(np.mean(np.concatenate(tally.base_spreads)))
    base_volume = float(np.mean(np.concatenate(tally.base_volumes)))
    ticks = np.maximum(tally.ticks, 1)
    return ChaseFlow(
        base_rate=tally.base_orders / max(tally.base_ticks, 1),
        base_size=size_distribution(np.concatenate(tally.base_sizes)),
        bin_ticks=bin_ticks,
        order_prob=tuple((tally.orders / ticks).tolist()),
        direction_prob=tuple((tally.with_jump / np.maximum(tally.orders, 1)).tolist()),
        widen=tuple(np.maximum((tally.spread / ticks - base_spread) / 2.0, 0.0).tolist()),
        thin=tuple(np.minimum(tally.volume / ticks / base_volume, 1.0).tolist()),
        chase_size=size_distribution(np.concatenate(tally.chase_sizes)),
    )
