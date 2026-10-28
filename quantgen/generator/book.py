"""Layer 2: the market-maker bot's order book.

The real books are built from independent quote layers. On each side, layer k sits at round(center -/+ half_width)
pushed out by a uniform jitter of 0..jitter ticks, is present with a fixed probability, and carries a volume drawn
from that layer's empirical distribution.
The visible levels are the present layers in order. For AMETHYST, for example, layers at 1, 3 and 5 ticks, each
present 100% / 70% / 70% of the time, reproduce the observed 9% missing L2 and 49% present L3 exactly.
"""

from dataclasses import dataclass

import numpy as np

from quantgen.market_day import LEVELS

MIN_PRICE = 0
MIN_VOLUME = 1


@dataclass(frozen=True)
class Layer:
    half_width: float
    jitter: int
    presence: float
    volumes: tuple[int, ...]
    volume_probs: tuple[float, ...]

    def draw_volumes(self, rng: np.random.Generator, count: int) -> np.ndarray:
        probs = np.asarray(self.volume_probs)
        return rng.choice(np.asarray(self.volumes), size=count, p=probs / probs.sum())


@dataclass(frozen=True)
class InnerQuote:
    """A short-lived quote pair inside the main spread (seen on TOFFEE_CAKE), on or off on both sides together."""

    start_prob: float
    stay_prob: float
    layer: Layer


@dataclass(frozen=True)
class BookParams:
    layers: tuple[Layer, ...]
    inner: InnerQuote | None = None

    def __post_init__(self) -> None:
        if not self.layers or self.layers[0].presence != 1.0:
            raise ValueError("the first book layer must always be present")
        ordered = ([self.inner.layer] if self.inner else []) + list(self.layers)
        for inner, outer in zip(ordered, ordered[1:], strict=False):
            if outer.half_width - inner.half_width <= inner.jitter:
                raise ValueError("book layers overlap: each layer must sit beyond the previous layer's jitter")


@dataclass(frozen=True)
class Book:
    bid_prices: np.ndarray
    bid_volumes: np.ndarray
    ask_prices: np.ndarray
    ask_volumes: np.ndarray


def round_half_up(values: np.ndarray) -> np.ndarray:
    return np.floor(values + 0.5)


def markov_switch(rng: np.random.Generator, ticks: int, start_prob: float, stay_prob: float) -> np.ndarray:
    """On/off state per tick: switches on with start_prob, stays on with stay_prob."""
    draws = rng.random(ticks)
    state = np.zeros(ticks, dtype=bool)
    on = False
    for tick in range(ticks):
        on = bool(draws[tick] < (stay_prob if on else start_prob))
        state[tick] = on
    return state


def _side(
    center: np.ndarray,
    layers: list[Layer],
    forced: list[np.ndarray | None],
    widen: np.ndarray,
    volume_scale: np.ndarray,
    sign: int,
    rng: np.random.Generator,
    level_drop: np.ndarray | None,
) -> tuple[np.ndarray, np.ndarray]:
    ticks = center.shape[0]
    prices = np.empty((ticks, len(layers)))
    volumes = np.empty((ticks, len(layers)))
    present = np.empty((ticks, len(layers)), dtype=bool)
    for k, (layer, always) in enumerate(zip(layers, forced, strict=True)):
        jitter = rng.integers(0, layer.jitter + 1, ticks)
        prices[:, k] = round_half_up(center + sign * (layer.half_width + widen)) + sign * jitter
        volumes[:, k] = np.maximum(np.round(layer.draw_volumes(rng, ticks) * volume_scale), MIN_VOLUME)
        present[:, k] = always if always is not None else rng.random(ticks) < layer.presence
        if level_drop is not None and always is None:
            present[:, k] &= rng.random(ticks) >= level_drop
    present &= prices >= MIN_PRICE

    order = np.argsort(~present, axis=1, kind="stable")[:, :LEVELS]
    rows = np.arange(ticks)[:, None]
    shown = present[rows, order]
    out_prices = np.where(shown, prices[rows, order], np.nan)
    out_volumes = np.where(shown, volumes[rows, order], np.nan)
    if out_prices.shape[1] < LEVELS:
        pad = np.full((ticks, LEVELS - out_prices.shape[1]), np.nan)
        out_prices, out_volumes = np.hstack([out_prices, pad]), np.hstack([out_volumes, pad])
    return out_prices, out_volumes


def build_book(
    center: np.ndarray,
    params: BookParams,
    rng: np.random.Generator,
    widen: np.ndarray | None = None,
    bid_scale: np.ndarray | None = None,
    ask_scale: np.ndarray | None = None,
    level_drop: np.ndarray | None = None,
) -> Book:
    """Quote a book around `center` each tick.

    `widen` pushes every layer out by that many ticks, and the scales thin each side's volumes (jump aftermath).
    `level_drop` is the per-tick chance that each layer beyond the first is pulled (a market maker withdrawing).
    The center is floored so the (widened) touch bid never goes below zero (far out-of-the-money vouchers).
    """
    ticks = center.shape[0]
    extra = np.zeros(ticks) if widen is None else widen
    touch = params.layers[0]
    center = np.maximum(center, touch.half_width + touch.jitter + extra)
    ones = np.ones(ticks)
    layers = list(params.layers)
    forced: list[np.ndarray | None] = [np.ones(ticks, dtype=bool)] + [None] * (len(layers) - 1)
    if params.inner is not None:
        inner_on = markov_switch(rng, ticks, params.inner.start_prob, params.inner.stay_prob)
        layers.insert(0, params.inner.layer)
        forced.insert(0, inner_on)
    bid_scale = ones if bid_scale is None else bid_scale
    ask_scale = ones if ask_scale is None else ask_scale
    bid_prices, bid_volumes = _side(center, layers, forced, extra, bid_scale, -1, rng, level_drop)
    ask_prices, ask_volumes = _side(center, layers, forced, extra, ask_scale, +1, rng, level_drop)
    return Book(bid_prices, bid_volumes, ask_prices, ask_volumes)
