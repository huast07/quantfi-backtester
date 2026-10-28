"""Event profiles: an effect that follows each event along a knot-interpolated curve of ticks since the event."""

from collections.abc import Sequence

import numpy as np


def knot_profile(since: np.ndarray, knots: Sequence[int], values: Sequence[float]) -> np.ndarray:
    """The curve at `since` ticks after an event: zero at 0, linear between knots, held after the last knot."""
    return np.interp(since, np.concatenate([[0.0], knots]), np.concatenate([[0.0], values]))


def profile_path(
    ticks: int, event_ticks: np.ndarray, weights: np.ndarray, knots: Sequence[int], values: Sequence[float]
) -> np.ndarray:
    """Sum over events of weight * curve(ticks since the event), per tick."""
    out = np.zeros(ticks)
    if not len(knots):
        return out
    for tick, weight in zip(event_ticks.tolist(), weights.tolist(), strict=True):
        out[tick:] += weight * knot_profile(np.arange(ticks - tick, dtype=float), knots, values)
    return out


def profile_basis(ticks: int, event_ticks: np.ndarray, weights: np.ndarray, knots: Sequence[int]) -> np.ndarray:
    """Columns whose combination with per-knot values gives `profile_path`: the summed weighted hat functions."""
    unit = np.eye(len(knots))
    return np.column_stack([profile_path(ticks, event_ticks, weights, knots, unit[i]) for i in range(len(knots))])


def convolved_profile(weights: np.ndarray, knots: Sequence[int], values: Sequence[float]) -> np.ndarray:
    """`profile_path` with an event (of that weight) at every tick: the weights convolved with the curve."""
    ticks = weights.shape[0]
    if not len(knots):
        return np.zeros(ticks)
    return np.convolve(weights, knot_profile(np.arange(ticks, dtype=float), knots, values))[:ticks]


def convolved_basis(weights: np.ndarray, knots: Sequence[int]) -> np.ndarray:
    """Columns whose combination with per-knot values gives `convolved_profile`."""
    unit = np.eye(len(knots))
    return np.column_stack([convolved_profile(weights, knots, unit[i]) for i in range(len(knots))])
