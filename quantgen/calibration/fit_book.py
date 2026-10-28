"""Fit the layered book model (generator/book.py) to real order books.

On ticks where all three levels are shown on both sides, level k is exactly layer k, so its full width
ask_k - bid_k is 2 * half_width + (two independent uniform jitters). That pins down half_width and jitter per
layer. Presence follows from how often a side shows 1, 2 or 3 levels, and each layer's volumes are bootstrapped
from that level on the same full-book ticks.
"""

from collections.abc import Sequence

import numpy as np

from quantgen.generator.book import BookParams, InnerQuote, Layer
from quantgen.market_day import LEVELS, ProductDay

MIN_WIDTH_SHARE = 0.01
MIN_INNER_SHARE = 0.02


def _stack(days: Sequence[ProductDay], masks: Sequence[np.ndarray] | None, attr: str) -> np.ndarray:
    arrays = [getattr(day, attr) for day in days]
    if masks is not None:
        arrays = [array[mask] for array, mask in zip(arrays, masks, strict=True)]
    return np.vstack(arrays)


def _width_run(widths: np.ndarray) -> tuple[int, int]:
    """Lowest width and jitter of the symmetric run of common widths around the mode."""
    values, counts = np.unique(widths, return_counts=True)
    common = set(values[counts >= MIN_WIDTH_SHARE * counts.sum()].astype(int).tolist())
    mode = int(values[np.argmax(counts)])
    low = mode
    while low - 1 in common:
        low -= 1
    high = mode
    while high + 1 in common:
        high += 1
    jitter = min(mode - low, high - mode)
    return mode - jitter, jitter


def _presence(bid_prices: np.ndarray, ask_prices: np.ndarray) -> tuple[float, float]:
    """Presence of layers 2 and 3 from the share of sides showing exactly 1 and exactly 3 levels."""
    shown = np.concatenate([(~np.isnan(bid_prices)).sum(axis=1), (~np.isnan(ask_prices)).sum(axis=1)])
    one, three = float(np.mean(shown == 1)), float(np.mean(shown == LEVELS))
    total = 1.0 - one + three
    spread = max(total**2 - 4.0 * three, 0.0) ** 0.5
    return (total + spread) / 2, (total - spread) / 2


def _volume_distribution(volumes: np.ndarray) -> tuple[tuple[int, ...], tuple[float, ...]]:
    values, counts = np.unique(volumes[~np.isnan(volumes)].astype(int), return_counts=True)
    return tuple(int(v) for v in values), tuple(float(c) for c in counts / counts.sum())


def _inner_quote(days: Sequence[ProductDay], outer_low: int) -> InnerQuote | None:
    """A quote pair inside the main spread, if one shows up on enough ticks (TOFFEE_CAKE)."""
    states, widths, volumes = [], [], []
    for day in days:
        width = day.ask_prices[:, 0] - day.bid_prices[:, 0]
        inner = width < outer_low
        states.append(inner)
        widths.append(width[inner])
        volumes.append(np.concatenate([day.bid_volumes[inner, 0], day.ask_volumes[inner, 0]]))
    on = np.concatenate(states)
    if on.mean() < MIN_INNER_SHARE:
        return None
    episodes = sum(int(np.sum(state[1:] & ~state[:-1]) + state[0]) for state in states)
    stay = 1.0 - episodes / on.sum()
    start = on.mean() * (1.0 - stay) / (1.0 - on.mean())
    low, jitter = _width_run(np.concatenate(widths))
    layer = Layer(low / 2, jitter, 1.0, *_volume_distribution(np.concatenate(volumes)))
    return InnerQuote(start_prob=start, stay_prob=stay, layer=layer)


def fit_book(days: Sequence[ProductDay], masks: Sequence[np.ndarray] | None = None) -> BookParams:
    """`masks` restricts the fit to calm ticks (TELLURIUM widens its book after jumps)."""
    bid_prices = _stack(days, masks, "bid_prices")
    ask_prices = _stack(days, masks, "ask_prices")
    volumes = np.vstack([_stack(days, masks, "bid_volumes"), _stack(days, masks, "ask_volumes")])
    full = ~np.isnan(bid_prices).any(axis=1) & ~np.isnan(ask_prices).any(axis=1)
    presence = (1.0, *_presence(bid_prices, ask_prices))

    layers = []
    for level in range(LEVELS):
        low, jitter = _width_run(ask_prices[full, level] - bid_prices[full, level])
        both_sides_full = np.concatenate([full, full])
        layers.append(Layer(low / 2, jitter, presence[level], *_volume_distribution(volumes[both_sides_full, level])))
    return BookParams(layers=tuple(layers), inner=_inner_quote(days, int(2 * layers[0].half_width)))
