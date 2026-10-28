"""Layer 3: takers, the participants whose trades form the market tape.

Real prints always sit at the same-tick touch and never exceed the touch volume, except TELLURIUM, where chasers
after a jump sweep into L2/L3 (one print per level touched).
"""

from dataclasses import dataclass
from typing import ClassVar

import numpy as np

from quantgen.generator.book import Book
from quantgen.generator.profiles import convolved_profile

CLUSTER_MAX_GAP = 10
BUY, SELL = 1, -1


@dataclass(frozen=True)
class SizeDistribution:
    sizes: tuple[int, ...]
    probs: tuple[float, ...]

    def draw(self, rng: np.random.Generator, count: int) -> np.ndarray:
        return rng.choice(np.asarray(self.sizes), size=count, p=np.asarray(self.probs) / sum(self.probs))

    def mean(self) -> float:
        return float(np.dot(self.sizes, self.probs) / sum(self.probs))


@dataclass(frozen=True)
class NoiseFlow:
    """Uninformed takers. `cluster_mean` > 1 makes arrivals come in bursts (TOFFEE_CAKE is over-dispersed)."""

    KIND: ClassVar[str] = "noise"
    rate: float
    buy_prob: float
    size: SizeDistribution
    cluster_mean: float = 1.0


@dataclass(frozen=True)
class IvRuleFlow:
    """Voucher takers: buy when the voucher is cheap to the smile, sell when rich, `consistency` of the time.

    They also wait for the mispricing: arrivals are proportional to |residual| ** `selectivity` (0 = uniform).
    """

    KIND: ClassVar[str] = "iv_rule"
    rate: float
    consistency: float
    size: SizeDistribution
    selectivity: float = 0.0


@dataclass(frozen=True)
class ChaseFlow:
    """Background noise plus jump chasers.

    For a while after each jump, orders arrive faster, lean in the jump's direction and sweep the book, and the
    market maker widens and thins its quotes on the side being chased. The profiles are indexed by
    `bin_ticks`-wide bins of time since the last jump.

    Unexpected flow in a post-jump window moves the quotes from the next tick on: each tick's signed volume minus
    the volume expected there (the usual chase after a jump), times `impact_per_lot` along `impact_knots` (ticks
    since; see profiles.knot_profile). Real TELLURIUM mids move ~0.5 per unexpected lot, permanently, and drift
    back a little on ticks where the expected chasers do not show up. Expected flow moves nothing on net, so the
    post-jump drift stays in the jump response.
    """

    KIND: ClassVar[str] = "chase"
    base_rate: float
    base_size: SizeDistribution
    bin_ticks: int
    order_prob: tuple[float, ...]
    direction_prob: tuple[float, ...]
    widen: tuple[float, ...]
    thin: tuple[float, ...]
    chase_size: SizeDistribution
    impact_knots: tuple[int, ...] = ()
    impact_per_lot: tuple[float, ...] = ()


Flow = NoiseFlow | IvRuleFlow | ChaseFlow


@dataclass(frozen=True)
class Tape:
    ticks: np.ndarray
    prices: np.ndarray
    quantities: np.ndarray


def arrival_ticks(
    rng: np.random.Generator, ticks: int, rate: float | np.ndarray, cluster_mean: float = 1.0
) -> np.ndarray:
    """At most one order per tick. Clusters start at rate / cluster_mean (a per-tick array is allowed) and have
    geometric size."""
    starts = np.flatnonzero(rng.random(ticks) < rate / cluster_mean)
    if cluster_mean <= 1.0:
        return starts
    members = [starts]
    sizes = rng.geometric(1.0 / cluster_mean, starts.shape[0])
    for begin, size in zip(starts, sizes, strict=True):
        if size > 1:
            members.append(begin + np.cumsum(rng.integers(1, CLUSTER_MAX_GAP + 1, size - 1)))
    merged = np.unique(np.concatenate(members))
    return merged[merged < ticks]


def hit_touch(book: Book, order_ticks: np.ndarray, sides: np.ndarray, sizes: np.ndarray) -> Tape:
    """Each order trades at the same-tick touch, capped at the touch volume."""
    buys = sides == BUY
    prices = np.where(buys, book.ask_prices[order_ticks, 0], book.bid_prices[order_ticks, 0])
    volumes = np.where(buys, book.ask_volumes[order_ticks, 0], book.bid_volumes[order_ticks, 0])
    valid = ~np.isnan(prices)
    quantities = np.minimum(sizes[valid], volumes[valid]).astype(np.int64)
    return Tape(order_ticks[valid].astype(np.int64), prices[valid], quantities)


def sweep(book: Book, order_ticks: np.ndarray, sides: np.ndarray, sizes: np.ndarray) -> Tape:
    """Each order walks the book from the touch, printing once per level it trades at."""
    out_ticks, out_prices, out_quantities = [], [], []
    for tick, side, size in zip(order_ticks.tolist(), sides.tolist(), sizes.tolist(), strict=True):
        prices = book.ask_prices[tick] if side == BUY else book.bid_prices[tick]
        volumes = book.ask_volumes[tick] if side == BUY else book.bid_volumes[tick]
        remaining = size
        for price, volume in zip(prices, volumes, strict=True):
            if remaining <= 0 or np.isnan(price):
                break
            filled = int(min(remaining, volume))
            out_ticks.append(tick)
            out_prices.append(price)
            out_quantities.append(filled)
            remaining -= filled
    return Tape(np.asarray(out_ticks, dtype=np.int64), np.asarray(out_prices), np.asarray(out_quantities, np.int64))


def noise_tape(
    flow: NoiseFlow,
    book: Book,
    rng: np.random.Generator,
    intensity: np.ndarray | None = None,
    buy_prob: np.ndarray | None = None,
) -> Tape:
    """`intensity` scales the arrival rate tick by tick and `buy_prob` replaces the flow's constant buy share."""
    rate = flow.rate if intensity is None else flow.rate * intensity
    ticks = arrival_ticks(rng, book.bid_prices.shape[0], rate, flow.cluster_mean)
    buy_share = flow.buy_prob if buy_prob is None else buy_prob[ticks]
    sides = np.where(rng.random(ticks.shape[0]) < buy_share, BUY, SELL)
    return hit_touch(book, ticks, sides, flow.size.draw(rng, ticks.shape[0]))


def selective_intensity(residual: np.ndarray, selectivity: float) -> np.ndarray:
    """Per-tick arrival weights proportional to |residual| ** selectivity, averaging one over the day."""
    if selectivity == 0.0:
        return np.ones(residual.shape[0])
    weight = np.abs(residual) ** selectivity
    mean = weight.mean()
    return weight / mean if mean > 0 else np.ones(residual.shape[0])


def iv_rule_tape(
    flow: IvRuleFlow, book: Book, residual: np.ndarray, rng: np.random.Generator, intensity: np.ndarray | None = None
) -> Tape:
    selective = selective_intensity(residual, flow.selectivity)
    rate = flow.rate * selective if intensity is None else flow.rate * selective * intensity
    ticks = arrival_ticks(rng, book.bid_prices.shape[0], rate)
    cheap = residual[ticks] < 0
    follows_rule = rng.random(ticks.shape[0]) < flow.consistency
    sides = np.where(cheap == follows_rule, BUY, SELL)
    return hit_touch(book, ticks, sides, flow.size.draw(rng, ticks.shape[0]))


def ticks_since_jump(ticks: int, jump_ticks: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Ticks since the most recent jump (-1 before the first) and the index of that jump."""
    positions = np.arange(ticks)
    index = np.searchsorted(jump_ticks, positions, side="right") - 1
    if jump_ticks.size == 0:
        return np.full(ticks, -1), index
    return np.where(index >= 0, positions - jump_ticks[np.maximum(index, 0)], -1), index


def chase_bins(flow: ChaseFlow, ticks: int, jump_ticks: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Profile bin per tick (-1 when outside every post-jump window) and the index of the last jump."""
    since, index = ticks_since_jump(ticks, jump_ticks)
    bins = np.where(since >= 0, since // flow.bin_ticks, -1)
    return np.where(bins < len(flow.order_prob), bins, -1), index


@dataclass(frozen=True)
class BookAdjustment:
    widen: np.ndarray
    bid_scale: np.ndarray
    ask_scale: np.ndarray


def chase_book_adjustment(
    flow: ChaseFlow, ticks: int, jump_ticks: np.ndarray, jump_signs: np.ndarray, rng: np.random.Generator
) -> BookAdjustment:
    """After a jump the market maker widens both sides (extra ticks, randomly rounded to whole ticks) and thins
    the side in the jump's direction (the asks after an up jump), which is the side the chasers hit."""
    bins, last = chase_bins(flow, ticks, jump_ticks)
    safe = np.maximum(bins, 0)
    mean_extra = np.where(bins >= 0, np.asarray(flow.widen)[safe], 0.0)
    scale = np.where(bins >= 0, np.asarray(flow.thin)[safe], 1.0)
    up = jump_signs[np.maximum(last, 0)] > 0 if len(jump_signs) else np.zeros(ticks, dtype=bool)
    return BookAdjustment(
        widen=np.floor(mean_extra + rng.random(ticks)),
        bid_scale=np.where(up, 1.0, scale),
        ask_scale=np.where(up, scale, 1.0),
    )


@dataclass(frozen=True)
class Orders:
    """Taker orders before they meet a book: one per tick at most."""

    ticks: np.ndarray
    sides: np.ndarray
    sizes: np.ndarray


def _order_prob(flow: ChaseFlow, bins: np.ndarray, intensity: np.ndarray | None) -> np.ndarray:
    order_prob = np.where(bins >= 0, np.asarray(flow.order_prob)[np.maximum(bins, 0)], flow.base_rate)
    return order_prob if intensity is None else np.minimum(order_prob * intensity, 1.0)


@dataclass(frozen=True)
class ChaseExpectation:
    """Per tick: whether it is inside a post-jump window, and the mean signed volume expected there."""

    in_window: np.ndarray
    volume: np.ndarray


def expect_chase(
    flow: ChaseFlow,
    ticks: int,
    jump_ticks: np.ndarray,
    jump_signs: np.ndarray,
    intensity: np.ndarray | None = None,
) -> ChaseExpectation:
    """Outside the windows sides are a coin flip, so the expected signed volume there is zero."""
    bins, last_jump = chase_bins(flow, ticks, jump_ticks)
    safe_bins = np.maximum(bins, 0)
    signs = jump_signs[np.maximum(last_jump, 0)] if len(jump_signs) else np.zeros(ticks)
    lean = 2.0 * np.asarray(flow.direction_prob)[safe_bins] - 1.0
    volume = np.where(bins >= 0, _order_prob(flow, bins, intensity) * lean * flow.chase_size.mean() * signs, 0.0)
    return ChaseExpectation(in_window=bins >= 0, volume=volume)


def chase_orders(
    flow: ChaseFlow,
    ticks: int,
    jump_ticks: np.ndarray,
    jump_signs: np.ndarray,
    rng: np.random.Generator,
    intensity: np.ndarray | None = None,
) -> Orders:
    """Orders do not depend on the book, so they can be drawn first and their impact put into the quotes."""
    bins, last_jump = chase_bins(flow, ticks, jump_ticks)
    in_window = bins >= 0
    safe_bins = np.maximum(bins, 0)
    order_prob = _order_prob(flow, bins, intensity)
    order_ticks = np.flatnonzero(rng.random(ticks) < order_prob)
    count = order_ticks.shape[0]

    chasing = in_window[order_ticks]
    signs = jump_signs[np.maximum(last_jump[order_ticks], 0)] if len(jump_signs) else np.ones(count)
    with_jump = rng.random(count) < np.asarray(flow.direction_prob)[safe_bins[order_ticks]]
    chase_sides = np.where(with_jump, signs, -signs)
    noise_sides = np.where(rng.random(count) < 0.5, BUY, SELL)
    sides = np.where(chasing, chase_sides, noise_sides).astype(np.int64)
    sizes = np.where(chasing, flow.chase_size.draw(rng, count), flow.base_size.draw(rng, count))
    return Orders(order_ticks.astype(np.int64), sides, sizes.astype(np.int64))


def unexpected_volume(orders: Orders, expectation: ChaseExpectation) -> np.ndarray:
    """Signed volume per tick minus what was expected there, inside the post-jump windows only: in calm markets the
    book is deep enough to absorb the odd order (real calm TELLURIUM mids barely move after one)."""
    volume = np.zeros(expectation.volume.shape[0])
    volume[orders.ticks] = orders.sides * orders.sizes
    return np.where(expectation.in_window, volume - expectation.volume, 0.0)


def impact_path(flow: ChaseFlow, orders: Orders, expectation: ChaseExpectation) -> np.ndarray:
    """How far unexpected flow has pushed the quotes, per tick (a tick's own flow shows from the next tick)."""
    return convolved_profile(unexpected_volume(orders, expectation), flow.impact_knots, flow.impact_per_lot)
