"""Variogram fits: V(k) = Var(x[t+k] - x[t]) separates a price process from i.i.d. quote noise.

Quote noise adds the same constant 2 * eta^2 at every lag, so fitting V(k) = model(k) + c recovers the process
parameters without being fooled by the bid/ask bounce that dominates 1-tick changes.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

RW_LAGS = (10, 20, 30, 50, 100)
TREND_LAGS = (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000)
OU_LAGS = (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000)
TREND_PHI_GRID = np.concatenate([np.linspace(0.0, 0.95, 20), 1.0 - np.logspace(-1.4, -4.0, 200)])
OU_DECAY_GRID = 1.0 - np.logspace(-5.0, -0.5, 400)


def variogram(paths: Sequence[np.ndarray], lags: Sequence[int]) -> np.ndarray:
    """Mean over days of the variance of k-tick changes (variance, not raw moment, so daily drift drops out)."""
    return np.array([np.mean([np.var(path[lag:] - path[:-lag]) for path in paths]) for lag in lags])


def _least_squares(design: np.ndarray, target: np.ndarray) -> tuple[np.ndarray, float]:
    """Least squares on relative errors, so long lags (large variances) do not swamp short ones."""
    weights = 1.0 / np.maximum(np.abs(target), 1e-12)
    coef, *_ = np.linalg.lstsq(design * weights[:, None], target * weights, rcond=None)
    return coef, float(np.sum(((design @ coef - target) * weights) ** 2))


@dataclass(frozen=True)
class RandomWalkFit:
    sigma: float
    noise_var: float


def fit_random_walk(paths: Sequence[np.ndarray], lags: Sequence[int] = RW_LAGS) -> RandomWalkFit:
    values = variogram(paths, lags)
    design = np.column_stack([np.asarray(lags, float), np.ones(len(lags))])
    (slope, intercept), _ = _least_squares(design, values)
    return RandomWalkFit(sigma=float(np.sqrt(max(slope, 0.0))), noise_var=max(float(intercept), 0.0) / 2)


@dataclass(frozen=True)
class LocalTrendFit:
    sigma: float
    trend_sd: float
    phi: float


def trend_shape(phi: float, lags: np.ndarray) -> np.ndarray:
    """Var of a k-tick sum of an AR(1) with unit stationary variance: k + 2 * sum_j (k - j) phi^j (closed form)."""
    if phi == 0.0:
        return lags.astype(float)
    tail = phi * (lags * (1.0 - phi) - (1.0 - phi**lags)) / (1.0 - phi) ** 2
    return lags + 2.0 * tail


def fit_local_trend(paths: Sequence[np.ndarray], lags: Sequence[int] = TREND_LAGS) -> LocalTrendFit:
    """V(k) = sigma^2 k + trend_var * shape(phi, k) + c, linear in (sigma^2, trend_var, c) for each phi."""
    values = variogram(paths, lags)
    lag_array = np.asarray(lags, float)
    best: tuple[float, float, float, float] | None = None
    for phi in TREND_PHI_GRID:
        design = np.column_stack([lag_array, trend_shape(float(phi), lag_array), np.ones(len(lags))])
        (diffusion_var, trend_var, _), error = _least_squares(design, values)
        if diffusion_var >= 0 and trend_var >= 0 and (best is None or error < best[3]):
            best = (float(phi), float(diffusion_var), float(trend_var), error)
    if best is None:
        rw = fit_random_walk(paths)
        return LocalTrendFit(sigma=rw.sigma, trend_sd=0.0, phi=0.0)
    phi, diffusion_var, trend_var, _ = best
    return LocalTrendFit(sigma=float(np.sqrt(diffusion_var)), trend_sd=float(np.sqrt(trend_var)), phi=phi)


@dataclass(frozen=True)
class MeanRevertingFit:
    kappa: float
    sigma: float
    noise_var: float


def fit_mean_reverting(paths: Sequence[np.ndarray], lags: Sequence[int] = OU_LAGS) -> MeanRevertingFit:
    """V(k) = 2 s^2 (1 - a^k) + c for an AR(1) level with stationary variance s^2."""
    values = variogram(paths, lags)
    lag_array = np.asarray(lags, float)
    best: tuple[float, float, float, float] | None = None
    for decay in OU_DECAY_GRID:
        design = np.column_stack([2.0 * (1.0 - decay**lag_array), np.ones(len(lags))])
        (stationary_var, intercept), error = _least_squares(design, values)
        if stationary_var > 0 and (best is None or error < best[3]):
            best = (float(decay), float(stationary_var), float(intercept), error)
    if best is None:
        raise ValueError("no mean-reverting fit: the variogram does not level off")
    decay, stationary_var, intercept, _ = best
    return MeanRevertingFit(
        kappa=1.0 - decay,
        sigma=float(np.sqrt(stationary_var * (1.0 - decay**2))),
        noise_var=max(intercept, 0.0) / 2,
    )


def significant_drift(paths: Sequence[np.ndarray], daily_sd: float, threshold: float = 2.0) -> float:
    """Per-tick drift if the mean daily move is `threshold` standard errors from zero, else 0."""
    moves = np.array([path[-1] - path[0] for path in paths])
    standard_error = daily_sd / np.sqrt(len(moves))
    if standard_error <= 0 or abs(moves.mean()) < threshold * standard_error:
        return 0.0
    return float(moves.mean() / (len(paths[0]) - 1))
