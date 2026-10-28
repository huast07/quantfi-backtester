"""Stylized facts from the EDA, computed the same way on real and generated days (the fidelity gate's inputs)."""

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from quantgen.calibration.fit_flow import trade_sides
from quantgen.calibration.fit_processes import find_jumps
from quantgen.calibration.fit_structure import implied_vol
from quantgen.generator.processes import TICKS_PER_DAY
from quantgen.generator.takers import BUY
from quantgen.market_day import MarketDay, ProductDay

LONG_LAG = 100
CORRELATION_LAG = 50
PEARLS = ("WHITE_PEARLS", "BLACK_PEARLS", "GOLDEN_PEARLS", "PINK_PEARLS", "BLUE_PEARLS")
PEARL_TOTAL = 50_000.0
BASKET = "FRUIT_BASKET"
BASKET_LEGS = {"DRAGONFRUIT": 2, "GRANADILLA": 3, "MANGOSTEEN": 1}
ATM_STRIKE = 7500
IV_SAMPLE_EVERY = 50
MIN_ROOM_FOR_L2 = 3
SAMPLING_BLOCKS = 10
VOUCHER_PREFIX = "VOUCHER_"
# About a hundred checks use a sampling term; z = 3.5 keeps the chance of any false alarm in a run near 5%
# (Bonferroni), where z = 2 would raise one or two by chance every run.
FAMILY_Z = 3.5


@dataclass(frozen=True)
class Tolerance:
    """A generated value passes if it lies in the real range widened by a margin: the largest of
    relative * |center|, absolute, and `sampling_z` standard errors of the real-vs-generated mean difference.

    The sampling term is for statistics that genuinely swing between days, such as the buy share of voucher takers
    who follow a mispricing whose sign persists for hundreds of ticks. Its `day_sd` comes from `batch_sd`.
    """

    relative: float = 0.0
    absolute: float = 0.0
    sampling_z: float = 0.0

    def margin(self, real: Sequence[float], generated: Sequence[float], day_sd: float = 0.0) -> float:
        center = (min(real) + max(real)) / 2
        fixed = max(self.relative * abs(center), self.absolute)
        if self.sampling_z <= 0:
            return fixed
        return max(fixed, self.sampling_z * day_sd * math.sqrt(1 / len(real) + 1 / len(generated)))


def slice_day(day: ProductDay, start: int, stop: int) -> ProductDay:
    keep = (day.trade_ticks >= start) & (day.trade_ticks < stop)
    return ProductDay(
        bid_prices=day.bid_prices[start:stop],
        bid_volumes=day.bid_volumes[start:stop],
        ask_prices=day.ask_prices[start:stop],
        ask_volumes=day.ask_volumes[start:stop],
        trade_ticks=day.trade_ticks[keep] - start,
        trade_prices=day.trade_prices[keep],
        trade_quantities=day.trade_quantities[keep],
    )


def batch_sd(
    compute: Callable[[ProductDay], float], days: Sequence[ProductDay], blocks: int = SAMPLING_BLOCKS
) -> float:
    """Standard deviation of a whole-day statistic by batch means: the spread of the statistic over a day's blocks,
    pooled over days, over sqrt(blocks). Blocks much longer than the flow's memory make this honest even for
    autocorrelated flow, and it never sees a difference between the days' means, so a biased generator cannot
    widen its own margin."""
    variances = []
    for day in days:
        edges = np.linspace(0, day.ticks, blocks + 1).astype(int)
        values = [compute(slice_day(day, a, b)) for a, b in zip(edges[:-1], edges[1:], strict=True)]
        variances.append(np.var(values, ddof=1))
    return float(np.sqrt(np.mean(variances) / blocks))


def _changes(mid: np.ndarray, lag: int) -> np.ndarray:
    return mid[lag::lag] - mid[:-lag:lag]


def tick_sigma(day: ProductDay) -> float:
    return float(np.std(np.diff(day.mid)))


def tick_acf(day: ProductDay) -> float:
    moves = np.diff(day.mid)
    return float(np.corrcoef(moves[1:], moves[:-1])[0, 1]) if np.std(moves) > 0 else 0.0


def long_sigma(day: ProductDay) -> float:
    return float(np.std(_changes(day.mid, LONG_LAG)))


def mean_spread(day: ProductDay) -> float:
    return float(np.mean(day.ask_prices[:, 0] - day.bid_prices[:, 0]))


def missing_l2(day: ProductDay) -> float:
    """Share of ticks without a second bid level, among ticks where the bid leaves room for one.

    A voucher worth a few coins near expiry cannot show a positive L2 bid, which is not a missing quote.
    """
    roomy = day.bid_prices[:, 0] >= MIN_ROOM_FOR_L2
    return float(np.mean(np.isnan(day.bid_prices[roomy, 1]))) if roomy.any() else 0.0


def prints(day: ProductDay) -> float:
    return float(day.trade_ticks.shape[0])


def mean_size(day: ProductDay) -> float:
    return float(np.mean(day.trade_quantities)) if day.trade_quantities.size else 0.0


def buy_share(day: ProductDay) -> float:
    return float(np.mean(trade_sides(day) == BUY)) if day.trade_ticks.size else 0.5


def taker_markout(day: ProductDay, horizon: int) -> float:
    """Mean side * (mid `horizon` ticks after the print - mid at the print): how informed the takers are, and so how
    much a passive quote that they fill loses (or a strategy that follows them earns)."""
    if not day.trade_ticks.size:
        return 0.0
    later = np.minimum(day.trade_ticks + horizon, day.ticks - 1)
    return float(np.mean(trade_sides(day) * (day.mid[later] - day.mid[day.trade_ticks])))


def _markout(horizon: int) -> Callable[[ProductDay], float]:
    return lambda day: taker_markout(day, horizon)


PRODUCT_STATS: Mapping[str, tuple[Callable[[ProductDay], float], Tolerance]] = {
    "tick sigma": (tick_sigma, Tolerance(relative=0.15)),
    "tick ACF(1)": (tick_acf, Tolerance(absolute=0.08)),
    "100-tick sigma": (long_sigma, Tolerance(relative=0.35)),
    "spread": (mean_spread, Tolerance(relative=0.05)),
    "missing L2": (missing_l2, Tolerance(absolute=0.02)),
    "prints/day": (prints, Tolerance(relative=0.25, absolute=5.0)),
    "mean size": (mean_size, Tolerance(relative=0.15)),
    "buy share": (buy_share, Tolerance(absolute=0.08, sampling_z=FAMILY_Z)),
    "taker markout 1": (_markout(1), Tolerance(absolute=0.25, sampling_z=FAMILY_Z)),
    "taker markout 10": (_markout(10), Tolerance(absolute=0.25, sampling_z=FAMILY_Z)),
    "taker markout 50": (_markout(50), Tolerance(absolute=0.5, sampling_z=FAMILY_Z)),
}


def pearl_sum_sd(market: MarketDay, _: float) -> float:
    total = sum(market.products[name].mid for name in PEARLS)
    return float(np.std(total - PEARL_TOTAL))


def _correlation(market: MarketDay, a: str, b: str) -> float:
    x = _changes(market.products[a].mid, CORRELATION_LAG)
    y = _changes(market.products[b].mid, CORRELATION_LAG)
    return float(np.corrcoef(x, y)[0, 1])


def white_black_correlation(market: MarketDay, _: float) -> float:
    return _correlation(market, "WHITE_PEARLS", "BLACK_PEARLS")


def jelly_peanut_correlation(market: MarketDay, _: float) -> float:
    return _correlation(market, "JELLY", "PEANUT_BUTTER")


def basket_premium_sigma(market: MarketDay, _: float) -> float:
    synthetic = sum(weight * market.products[leg].mid for leg, weight in BASKET_LEGS.items())
    return float(np.std(_changes(market.products[BASKET].mid - synthetic, LONG_LAG)))


def tellurium_jumps(market: MarketDay, _: float) -> float:
    return float(find_jumps(market.products["TELLURIUM"].mid).ticks.shape[0])


def atm_iv(market: MarketDay, days_to_expiry_at_open: float) -> float:
    sample = slice(0, None, IV_SAMPLE_EVERY)
    spot = market.products["LYCHEE"].mid[sample]
    price = market.products[f"VOUCHER_{ATM_STRIKE}"].mid[sample]
    days = days_to_expiry_at_open - np.arange(market.ticks)[sample] / TICKS_PER_DAY
    return float(np.median(implied_vol(price, spot, ATM_STRIKE, days)))


def voucher_taker_markout(market: MarketDay, horizon: int) -> float:
    """`taker_markout` over every voucher print of the day. One strike's is too noisy to tell informed takers
    from uninformed ones; pooled over the ten strikes the difference is plain."""
    moves = []
    for name, day in market.products.items():
        if name.startswith(VOUCHER_PREFIX) and day.trade_ticks.size:
            later = np.minimum(day.trade_ticks + horizon, day.ticks - 1)
            moves.append(trade_sides(day) * (day.mid[later] - day.mid[day.trade_ticks]))
    return float(np.mean(np.concatenate(moves))) if moves else 0.0


def _voucher_markout(horizon: int) -> Callable[[MarketDay, float], float]:
    return lambda market, _: voucher_taker_markout(market, horizon)


MARKET_STATS: Mapping[str, tuple[Callable[[MarketDay, float], float], Tolerance]] = {
    "pearl sum sd": (pearl_sum_sd, Tolerance(relative=0.3)),
    "WHITE-BLACK corr": (white_black_correlation, Tolerance(absolute=0.12)),
    "JELLY-PEANUT corr": (jelly_peanut_correlation, Tolerance(absolute=0.12)),
    "basket premium 100-tick sigma": (basket_premium_sigma, Tolerance(relative=0.35)),
    "TELLURIUM jumps/day": (tellurium_jumps, Tolerance(relative=0.4)),
    "ATM IV": (atm_iv, Tolerance(absolute=0.002)),
    "voucher taker markout 10": (_voucher_markout(10), Tolerance(absolute=0.06)),
    "voucher taker markout 50": (_voucher_markout(50), Tolerance(absolute=0.2)),
}
