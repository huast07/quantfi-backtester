"""Fit single-product fair-value processes, quote noise and the innovation correlation matrix."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from quantgen.calibration.variogram import (
    fit_local_trend,
    fit_mean_reverting,
    fit_random_walk,
    significant_drift,
    trend_shape,
)
from quantgen.generator.book import BookParams, build_book
from quantgen.generator.processes import (
    TICKS_PER_DAY,
    Constant,
    JumpDiffusion,
    JumpResponse,
    LocalTrend,
    MeanReverting,
    RandomWalk,
    Steps,
    jump_response_path,
)
from quantgen.generator.profiles import convolved_basis, convolved_profile, profile_basis

JUMP_THRESHOLD = 50.0
RESPONSE_KNOTS = (10, 50, 100, 200, 300, 400, 600)
IMPACT_KNOTS = (1, 2, 5, 20, 50, 200)
STEP_SMOOTHING = 21
STEP_LOOKAROUND = 10
STEP_MOVE = 5.0
STEP_MERGE_GAP = 20
CORRELATION_LAG = 50
MIN_CORRELATION = 0.1
NOISE_SIMULATION_SEED = 20261027


def fit_constant(mids: Sequence[np.ndarray]) -> Constant:
    return Constant(level=float(np.round(np.median(np.concatenate(mids)))))


def fit_random_walk_process(mids: Sequence[np.ndarray]) -> RandomWalk:
    fit = fit_random_walk(mids)
    return RandomWalk(sigma=fit.sigma, drift=significant_drift(mids, fit.sigma * np.sqrt(TICKS_PER_DAY)))


def fit_local_trend_process(mids: Sequence[np.ndarray], with_drift: bool = True) -> LocalTrend:
    fit = fit_local_trend(mids)
    if not with_drift:
        return LocalTrend(sigma=fit.sigma, trend_sd=fit.trend_sd, phi=fit.phi)
    day = np.array([float(TICKS_PER_DAY)])
    daily_var = fit.sigma**2 * TICKS_PER_DAY + fit.trend_sd**2 * float(trend_shape(fit.phi, day)[0])
    drift = significant_drift(mids, float(np.sqrt(daily_var)))
    return LocalTrend(sigma=fit.sigma, trend_sd=fit.trend_sd, phi=fit.phi, drift=drift)


def fit_mean_reverting_process(mids: Sequence[np.ndarray]) -> MeanReverting:
    fit = fit_mean_reverting(mids)
    return MeanReverting(mean=float(np.mean(np.concatenate(mids))), kappa=fit.kappa, sigma=fit.sigma)


@dataclass(frozen=True)
class Jumps:
    ticks: np.ndarray
    signs: np.ndarray
    sizes: np.ndarray


def find_jumps(mid: np.ndarray, threshold: float = JUMP_THRESHOLD) -> Jumps:
    """Jump at tick j = a move larger than `threshold` from tick j-1 to tick j."""
    moves = np.diff(mid)
    index = np.flatnonzero(np.abs(moves) > threshold)
    return Jumps(ticks=(index + 1).astype(np.int64), signs=np.sign(moves[index]), sizes=np.abs(moves[index]))


def remove_jumps(mid: np.ndarray, jumps: Jumps) -> np.ndarray:
    moves = np.diff(mid)
    moves[jumps.ticks - 1] = 0.0
    return np.concatenate([[mid[0]], mid[0] + np.cumsum(moves)])


def direction_concentration(jumps: Sequence[Jumps]) -> float:
    """Beta(c, c) concentration of the daily up-probability, by moments with a binomial correction."""
    counts = np.array([len(day.signs) for day in jumps], dtype=float)
    shares = np.array([np.mean(day.signs > 0) if len(day.signs) else 0.5 for day in jumps])
    excess = np.var(shares) - np.mean(shares * (1 - shares) / np.maximum(counts, 1))
    if excess <= 0:
        return 5.0
    return float(np.clip((0.25 / excess - 1.0) / 2.0, 0.2, 5.0))


@dataclass(frozen=True)
class JumpDynamics:
    response: JumpResponse
    impact_per_lot: tuple[float, ...]


def _dynamics_design(
    ticks: int,
    jumps: Jumps,
    surprise: np.ndarray | None,
    response_knots: Sequence[int],
    impact_knots: Sequence[int],
    reference_size: float,
) -> np.ndarray:
    columns = [
        profile_basis(ticks, jumps.ticks, jumps.signs, response_knots),
        profile_basis(ticks, jumps.ticks, jumps.signs * (jumps.sizes - reference_size), response_knots),
    ]
    if surprise is not None and len(impact_knots):
        columns.append(convolved_basis(surprise, impact_knots))
    return np.hstack(columns)


def fit_jump_dynamics(
    mids: Sequence[np.ndarray],
    jumps: Sequence[Jumps],
    surprises: Sequence[np.ndarray] | None = None,
    response_knots: Sequence[int] = RESPONSE_KNOTS,
    impact_knots: Sequence[int] = IMPACT_KNOTS,
) -> JumpDynamics:
    """Least squares of the jump-removed tick changes on every jump's response and on the impact of every tick's
    unexpected taker volume (`surprises`, see takers.unexpected_volume), all at once."""
    reference_size = float(np.mean(np.concatenate([day.sizes for day in jumps])))
    day_surprises = surprises if surprises is not None else [None] * len(mids)
    designs, targets = [], []
    for mid, day, surprise in zip(mids, jumps, day_surprises, strict=True):
        design = _dynamics_design(mid.shape[0], day, surprise, response_knots, impact_knots, reference_size)
        designs.append(np.diff(design, axis=0))
        targets.append(np.diff(remove_jumps(mid, day)))
    coef, *_ = np.linalg.lstsq(np.vstack(designs), np.concatenate(targets), rcond=None)
    k = len(response_knots)
    response = JumpResponse(
        knots=tuple(int(knot) for knot in response_knots),
        drift=tuple(float(c) for c in coef[:k]),
        size_slope=tuple(float(c) for c in coef[k : 2 * k]),
        reference_size=reference_size,
    )
    return JumpDynamics(response=response, impact_per_lot=tuple(float(c) for c in coef[2 * k :]))


@dataclass(frozen=True)
class JumpFit:
    process: JumpDiffusion
    jumps: list[Jumps]
    impact_per_lot: tuple[float, ...]
    calm_mids: list[np.ndarray]


def fit_jump_diffusion(mids: Sequence[np.ndarray], surprises: Sequence[np.ndarray] | None = None) -> JumpFit:
    """Jumps, then their response and the takers' impact, then the diffusion left once all three are taken out."""
    jumps = [find_jumps(mid) for mid in mids]
    dynamics = fit_jump_dynamics(mids, jumps, surprises)
    day_surprises = surprises if surprises is not None else [None] * len(mids)
    calm_mids = []
    for mid, day, surprise in zip(mids, jumps, day_surprises, strict=True):
        ticks = mid.shape[0]
        calm = remove_jumps(mid, day) - jump_response_path(dynamics.response, ticks, day.ticks, day.signs, day.sizes)
        if surprise is not None:
            calm = calm - convolved_profile(surprise, IMPACT_KNOTS, dynamics.impact_per_lot)
        calm_mids.append(calm)
    process = JumpDiffusion(
        diffusion=fit_local_trend_process(calm_mids, False),
        jumps_per_day=sum(len(day.ticks) for day in jumps) / len(mids),
        jump_sizes=tuple(float(size) for day in jumps for size in day.sizes),
        direction_concentration=direction_concentration(jumps),
        response=dynamics.response,
    )
    return JumpFit(process, jumps, dynamics.impact_per_lot, calm_mids)


def _rolling_median(values: np.ndarray, window: int) -> np.ndarray:
    pad = window // 2
    padded = np.concatenate([np.full(pad, values[0]), values, np.full(pad, values[-1])])
    return np.median(sliding_window_view(padded, window), axis=1)


def _segments(flags: np.ndarray, merge_gap: int) -> list[tuple[int, int]]:
    edges = np.flatnonzero(np.diff(np.concatenate([[0], flags.astype(int), [0]])))
    merged: list[tuple[int, int]] = []
    for begin, end in zip(edges[::2].tolist(), edges[1::2].tolist(), strict=True):
        if merged and begin - merged[-1][1] < merge_gap:
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((begin, end))
    return merged


@dataclass(frozen=True)
class StepEvent:
    day: int
    begin: int
    end: int
    size: float


def find_steps(mids: Sequence[np.ndarray]) -> list[StepEvent]:
    """Ramps where a 21-tick rolling median moves more than STEP_MOVE across +/- STEP_LOOKAROUND ticks."""
    events = []
    k = STEP_LOOKAROUND
    for day, mid in enumerate(mids):
        smooth = _rolling_median(mid, STEP_SMOOTHING)
        moving = np.zeros(mid.shape[0], dtype=bool)
        moving[k:-k] = np.abs(smooth[2 * k :] - smooth[: -2 * k]) > STEP_MOVE
        for begin, end in _segments(moving, STEP_MERGE_GAP):
            first, last = max(begin - k, 0), min(end + k, mid.shape[0] - 1)
            events.append(StepEvent(day, first, last, float(smooth[last] - smooth[first])))
    return events


def step_absorbers(events: Sequence[StepEvent], members: Mapping[str, Sequence[np.ndarray]]) -> dict[str, float]:
    """Share of each step that each member moves against it: -sum(member move * step) / sum(step^2)."""
    sizes = np.array([event.size for event in events])
    if not sizes.size or not np.any(sizes):
        return {name: 0.0 for name in members}
    shares = {}
    for name, mids in members.items():
        moves = np.array([mids[e.day][e.end] - mids[e.day][e.begin] for e in events])
        shares[name] = float(-np.sum(moves * sizes) / np.sum(sizes**2))
    return shares


def fit_steps(mids: Sequence[np.ndarray], members: Mapping[str, Sequence[np.ndarray]]) -> Steps:
    events = find_steps(mids)
    if not events:
        return Steps(daily_counts=(0,), step_sizes=(0.0,), ramp_ticks=1, absorbers={})
    return Steps(
        daily_counts=tuple(sum(event.day == day for event in events) for day in range(len(mids))),
        step_sizes=tuple(event.size for event in events),
        ramp_ticks=max(int(np.median([event.end - event.begin for event in events])), 1),
        absorbers=step_absorbers(events, members),
    )


def tick_variance(mids: Sequence[np.ndarray]) -> float:
    return float(np.mean([np.var(np.diff(mid)) for mid in mids]))


def quote_noise_sd(mids: Sequence[np.ndarray], fair_paths: Sequence[np.ndarray], book: BookParams) -> float:
    """Extra i.i.d. noise on the quote center, beyond what the book's rounding and jitter already produce.

    Books are simulated on fair paths that carry the fitted process but no extra noise. Any 1-tick variance the
    real mid has beyond that is attributed to noise: each unit of noise variance adds 2 to Var(delta mid).
    """
    rng = np.random.default_rng(NOISE_SIMULATION_SEED)
    simulated = []
    for path in fair_paths:
        book_sim = build_book(path, book, rng)
        simulated.append((book_sim.bid_prices[:, 0] + book_sim.ask_prices[:, 0]) / 2)
    excess = tick_variance(mids) - tick_variance(simulated)
    return float(np.sqrt(max(excess, 0.0) / 2.0))


def correlation(
    mids: Mapping[str, Sequence[np.ndarray]],
    names: Sequence[str],
    model_sd: Mapping[str, float],
    lag: int = CORRELATION_LAG,
) -> np.ndarray:
    """Innovation correlations that make the generator reproduce the real covariance of `lag`-tick changes.

    The real covariance is divided by the generator's own change sd per product (`model_sd`), not the real one,
    so small errors in the marginal fits do not distort sums of nearly offsetting products (the pearls).
    Entries must agree in sign on every day and be at least MIN_CORRELATION in size; the result is then projected
    to the nearest valid correlation matrix.
    """
    days = len(next(iter(mids.values())))
    scale = np.array([model_sd[name] for name in names])
    daily = []
    for day in range(days):
        changes = np.column_stack([mids[name][day][lag::lag] - mids[name][day][:-lag:lag] for name in names])
        daily.append(np.cov(changes, rowvar=False) / np.outer(scale, scale))
    stacked = np.array(daily)
    mean = stacked.mean(axis=0)
    consistent = np.all(np.sign(stacked) == np.sign(mean), axis=0) & (np.abs(mean) >= MIN_CORRELATION)
    matrix = np.where(consistent, mean, 0.0)
    np.fill_diagonal(matrix, 1.0)
    return nearest_correlation(matrix)


def change_sd(paths: Sequence[np.ndarray], lag: int = CORRELATION_LAG) -> float:
    return float(np.sqrt(np.mean([np.var(path[lag::lag] - path[:-lag:lag]) for path in paths])))


def nearest_correlation(matrix: np.ndarray, floor: float = 1e-6) -> np.ndarray:
    values, vectors = np.linalg.eigh((matrix + matrix.T) / 2)
    repaired = vectors @ np.diag(np.maximum(values, floor)) @ vectors.T
    scale = np.sqrt(np.diag(repaired))
    return repaired / np.outer(scale, scale)
