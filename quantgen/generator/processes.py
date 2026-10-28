"""Layer 1: hidden fair-value processes, one per price archetype found in the EDA.

Every simulator takes its own standard-normal innovations `z`, so correlated products can share a Cholesky draw.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import ClassVar

import numpy as np

from quantgen.generator.profiles import profile_path

TICKS_PER_DAY = 10_000
TREND_FILTER_STEPS = 60
MIN_JUMP_LEVEL = 0.1


@dataclass(frozen=True)
class Constant:
    KIND: ClassVar[str] = "constant"
    level: float


@dataclass(frozen=True)
class RandomWalk:
    KIND: ClassVar[str] = "random_walk"
    sigma: float
    drift: float = 0.0


@dataclass(frozen=True)
class MeanReverting:
    """Discrete Ornstein-Uhlenbeck: x += kappa * (mean - x) + sigma * z."""

    KIND: ClassVar[str] = "mean_reverting"
    mean: float
    kappa: float
    sigma: float


@dataclass(frozen=True)
class LocalTrend:
    """Random walk plus a slowly varying trend: x += drift + mu + sigma * noise, mu an AR(1) of persistence phi.

    `trend_sd` is mu's stationary sd. This is the momentum model (BLUE_PEARLS, TELLURIUM between jumps).
    """

    KIND: ClassVar[str] = "local_trend"
    sigma: float
    trend_sd: float
    phi: float
    drift: float = 0.0


@dataclass(frozen=True)
class Steps:
    """Flat plateaus broken by ramps: each step moves the level by a size drawn from `step_sizes` over `ramp_ticks`.

    The number of steps in a day is drawn from `daily_counts`, the counts seen on the real days (0, 1 and 2), so a
    regular day never has more steps than a real one did. Days with more steps are a stress case, not a regular day.

    Other products absorb each step in the given shares, so a conserved total is kept during the ramp (when
    GOLDEN_PEARLS steps down 100, WHITE, BLACK and BLUE rise by about 100 between them).
    """

    KIND: ClassVar[str] = "steps"
    daily_counts: tuple[int, ...]
    step_sizes: tuple[float, ...]
    ramp_ticks: int
    absorbers: Mapping[str, float]


@dataclass(frozen=True)
class JumpResponse:
    """How the price moves after a jump, in the jump's direction: drift(k) + size_slope(k) * (size - reference_size)
    at k ticks after it, linear between `knots` (and zero at k = 0), held after the last knot.

    TELLURIUM: a typical jump is followed by ~+20 over 200 ticks that fades by ~500, and a jump bigger than typical
    gives most of the excess back within ~200 ticks (slope ~ -1.3), a smaller one is topped up.
    """

    knots: tuple[int, ...]
    drift: tuple[float, ...]
    size_slope: tuple[float, ...]
    reference_size: float


@dataclass(frozen=True)
class JumpDiffusion:
    """Diffusion plus one-tick jumps, each followed by its `response` (none: the jump is simply permanent).

    Each day draws an up-probability from Beta(c, c), so jumps can cluster in one direction
    (TELLURIUM: 7 of 8 down on day -2, 9 of 9 up on day -1).
    """

    KIND: ClassVar[str] = "jump_diffusion"
    diffusion: LocalTrend
    jumps_per_day: float
    jump_sizes: tuple[float, ...]
    direction_concentration: float
    response: JumpResponse | None = None


@dataclass(frozen=True)
class Basket:
    """Weighted sum of leg fair values plus a random-walk premium (which starts at the day-0 close premium)."""

    KIND: ClassVar[str] = "basket"
    legs: Mapping[str, int]
    premium_sigma: float


@dataclass(frozen=True)
class Plug:
    """Plateaus that jump to restore sum(members) + self = total, with a hazard that rises with the deviation."""

    KIND: ClassVar[str] = "plug"
    members: tuple[str, ...]
    total: float
    hazard_edges: tuple[float, ...]
    hazard_probs: tuple[float, ...]
    slope: float
    residual_sd: float


@dataclass(frozen=True)
class Voucher:
    """Black-Scholes call on `underlying` priced off the shared smile, plus an AR(1) per-strike mispricing."""

    KIND: ClassVar[str] = "voucher"
    underlying: str
    strike: int
    residual_sd: float
    residual_phi: float


@dataclass(frozen=True)
class VoucherSurface:
    """IV per sqrt-day = level + factor + skew * m + curvature * m^2, with m = ln(K / S) / sqrt(T) and T in days.

    The factor is an AR(1) shared by every strike (the ATM IV wanders 1.7-2.2% within a day). It starts where
    day 0 closed.
    By default the smile moves with LYCHEE (sticky delta, as fitted). With `sticky_strike`, moneyness is measured
    from the opening spot instead, so each strike keeps its IV as LYCHEE moves (Derman, 1999).
    """

    days_to_expiry: float
    iv_level: float
    skew: float
    curvature: float
    factor_start: float
    factor_sd: float
    factor_phi: float
    sticky_strike: bool = False


Process = Constant | RandomWalk | MeanReverting | LocalTrend | Steps | JumpDiffusion | Basket | Plug | Voucher


@dataclass(frozen=True)
class FairValue:
    path: np.ndarray
    jump_ticks: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int64))
    jump_signs: np.ndarray = field(default_factory=lambda: np.empty(0))
    residual: np.ndarray | None = None


def ar1(z: np.ndarray, phi: float, scale: float, first: float = 0.0) -> np.ndarray:
    out = np.empty_like(z)
    previous = first
    for tick, shock in enumerate(z):
        previous = phi * previous + scale * shock
        out[tick] = previous
    return out


def constant(process: Constant, ticks: int) -> FairValue:
    return FairValue(np.full(ticks, process.level))


def random_walk(process: RandomWalk, start: float, z: np.ndarray) -> FairValue:
    return FairValue(start + np.cumsum(process.drift + process.sigma * z))


def mean_reverting(process: MeanReverting, start: float, z: np.ndarray) -> FairValue:
    deviation = ar1(z, 1.0 - process.kappa, process.sigma, first=start - process.mean)
    return FairValue(process.mean + deviation)


def trend_filter(process: LocalTrend) -> tuple[float, float]:
    """Loadings (c, tau) such that d = c*z + e, e = phi*e_prev + tau*z, all driven by one innovation z.

    This has the same variogram as the fitted model (i.i.d. sigma noise plus an independent AR(1) trend with
    stationary sd trend_sd). Driving both parts with the product's own z keeps its correlation with other products:
    tick by tick, BLUE_PEARLS moves against WHITE + BLACK at about -0.6 on the real days.
    """
    trend_var, noise_var, phi = process.trend_sd**2, process.sigma**2, process.phi
    if trend_var == 0.0:
        return process.sigma, 0.0

    def excess(tau: float) -> float:
        c = (-tau + math.sqrt(tau**2 + 4.0 * noise_var)) / 2.0
        return c * tau + tau**2 / (1.0 - phi**2) - trend_var

    low, high = 0.0, math.sqrt(trend_var * (1.0 - phi**2))
    for _ in range(TREND_FILTER_STEPS):
        middle = (low + high) / 2
        low, high = (middle, high) if excess(middle) < 0 else (low, middle)
    tau = (low + high) / 2
    return (-tau + math.sqrt(tau**2 + 4.0 * noise_var)) / 2.0, tau


def trend_increments(process: LocalTrend, z: np.ndarray) -> np.ndarray:
    c, tau = trend_filter(process)
    return process.drift + c * z + ar1(z, process.phi, tau)


def local_trend(process: LocalTrend, start: float, z: np.ndarray) -> FairValue:
    return FairValue(start + np.cumsum(trend_increments(process, z)))


def steps(process: Steps, start: float, ticks: int, rng: np.random.Generator) -> FairValue:
    count = int(rng.choice(process.daily_counts))
    path = np.full(ticks, start)
    ramp = np.linspace(1.0 / process.ramp_ticks, 1.0, process.ramp_ticks)
    for begin in np.sort(rng.integers(0, ticks, count)):
        size = float(rng.choice(process.step_sizes))
        shape = np.ones(ticks - begin)
        length = min(process.ramp_ticks, ticks - begin)
        shape[:length] = ramp[:length]
        path[begin:] += size * shape
    return FairValue(path)


def jump_response_path(
    response: JumpResponse, ticks: int, jump_ticks: np.ndarray, signs: np.ndarray, sizes: np.ndarray
) -> np.ndarray:
    """The summed post-jump responses, per tick."""
    drift = profile_path(ticks, jump_ticks, signs, response.knots, response.drift)
    excess = signs * (sizes - response.reference_size)
    return drift + profile_path(ticks, jump_ticks, excess, response.knots, response.size_slope)


def jump_diffusion(process: JumpDiffusion, start: float, z: np.ndarray, rng: np.random.Generator) -> FairValue:
    """Diffusion plus permanent jumps. A jump that would take the price below MIN_JUMP_LEVEL of the open goes the
    other way instead, so even a stress case with many large same-direction jumps keeps a positive price."""
    ticks = z.shape[0]
    count = min(rng.poisson(process.jumps_per_day * ticks / TICKS_PER_DAY), ticks)
    jump_ticks = np.sort(rng.choice(ticks, size=count, replace=False)).astype(np.int64)
    up_prob = rng.beta(process.direction_concentration, process.direction_concentration)
    signs = np.where(rng.random(count) < up_prob, 1.0, -1.0)
    sizes = rng.choice(process.jump_sizes, size=count) if count else np.empty(0)
    diffusion = start + np.cumsum(trend_increments(process.diffusion, z))
    floor = MIN_JUMP_LEVEL * start
    jumped = 0.0
    for i, (tick, size) in enumerate(zip(jump_ticks.tolist(), sizes.tolist(), strict=True)):
        if diffusion[tick] + jumped - size < floor and signs[i] < 0:
            signs[i] = 1.0
        jumped += signs[i] * size
    moves = np.zeros(ticks)
    moves[jump_ticks] = signs * sizes
    path = diffusion + np.cumsum(moves)
    if process.response is not None:
        path = path + jump_response_path(process.response, ticks, jump_ticks, signs, sizes)
    return FairValue(path, jump_ticks=jump_ticks, jump_signs=signs)


def basket(
    process: Basket, start: float, legs: Mapping[str, np.ndarray], leg_starts: Mapping[str, float], z: np.ndarray
) -> FairValue:
    synthetic = sum(weight * legs[name] for name, weight in process.legs.items())
    premium_start = start - sum(weight * leg_starts[name] for name, weight in process.legs.items())
    return FairValue(synthetic + premium_start + np.cumsum(process.premium_sigma * z))


def plug(process: Plug, start: float, member_sum: np.ndarray, rng: np.random.Generator) -> FairValue:
    ticks = member_sum.shape[0]
    draws = rng.random(ticks)
    noise = rng.standard_normal(ticks) * process.residual_sd
    edges = np.asarray(process.hazard_edges)
    probs = np.asarray(process.hazard_probs)
    path = np.empty(ticks)
    level = start
    for tick in range(ticks):
        deviation = member_sum[tick] + level - process.total
        if draws[tick] < probs[np.searchsorted(edges, abs(deviation), side="right") - 1]:
            level += process.slope * deviation + noise[tick]
        path[tick] = level
    return FairValue(path)


_erf = np.frompyfunc(math.erf, 1, 1)


def norm_cdf(x: np.ndarray) -> np.ndarray:
    return 0.5 * (1.0 + _erf(np.asarray(x, dtype=float) / math.sqrt(2.0)).astype(float))


def black_scholes_call(spot: np.ndarray, strike: float, days: np.ndarray, vol: np.ndarray) -> np.ndarray:
    root_t = np.sqrt(np.maximum(days, 1e-9))
    d1 = (np.log(spot / strike) + 0.5 * vol**2 * days) / (vol * root_t)
    return spot * norm_cdf(d1) - strike * norm_cdf(d1 - vol * root_t)


def smile_vol(
    surface: VoucherSurface, spot: np.ndarray, strike: float, days: np.ndarray, factor: np.ndarray | float = 0.0
) -> np.ndarray:
    moneyness = np.log(strike / spot) / np.sqrt(np.maximum(days, 1e-9))
    level = surface.iv_level + factor
    return np.maximum(level + surface.skew * moneyness + surface.curvature * moneyness**2, 1e-4)


def iv_factor(surface: VoucherSurface, ticks: int, rng: np.random.Generator) -> np.ndarray:
    innovation_sd = surface.factor_sd * math.sqrt(1.0 - surface.factor_phi**2)
    return ar1(rng.standard_normal(ticks), surface.factor_phi, innovation_sd, first=surface.factor_start)


def days_left(surface: VoucherSurface, ticks: int) -> np.ndarray:
    return surface.days_to_expiry - np.arange(ticks) / TICKS_PER_DAY


def voucher(
    process: Voucher, surface: VoucherSurface, spot: np.ndarray, factor: np.ndarray, rng: np.random.Generator
) -> FairValue:
    """Price off the moving smile plus an idiosyncratic AR(1) mispricing. `residual` is that idiosyncratic part,
    which is what the IV-rule takers trade on (it reverts within the day; the shared factor does not)."""
    days = days_left(surface, spot.shape[0])
    anchor = np.full_like(spot, spot[0]) if surface.sticky_strike else spot
    moving = black_scholes_call(spot, process.strike, days, smile_vol(surface, anchor, process.strike, days, factor))
    innovation_sd = process.residual_sd * math.sqrt(1.0 - process.residual_phi**2)
    idiosyncratic = ar1(rng.standard_normal(spot.shape[0]), process.residual_phi, innovation_sd)
    return FairValue(moving + idiosyncratic, residual=idiosyncratic)
