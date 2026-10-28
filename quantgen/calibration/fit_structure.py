"""Fit the cross-product structures: the pearl-sum plug, the fruit basket, and the voucher smile."""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from quantgen.calibration.variogram import fit_mean_reverting, fit_random_walk
from quantgen.generator.book import Layer
from quantgen.generator.processes import (
    TICKS_PER_DAY,
    Basket,
    Plug,
    Voucher,
    VoucherSurface,
    black_scholes_call,
    norm_cdf,
    smile_vol,
)

PLUG_JUMP_THRESHOLD = 3.0
PLUG_HAZARD_EDGES = (0.0, 5.0, 10.0, 15.0, 20.0, 30.0)
BASKET_REGRESSION_LAG = 100
SMILE_SAMPLE_EVERY = 20
IV_BISECTION_STEPS = 40
IV_MAX = 0.2


def fit_plug(plug: Sequence[np.ndarray], members: Sequence[Sequence[np.ndarray]], names: Sequence[str]) -> Plug:
    """`plug` and each of `members` hold one mid path per day."""
    sums = [p + sum(member[day] for member in members) for day, p in enumerate(plug)]
    total = float(np.round(np.mean(np.concatenate(sums))))
    deviation = np.concatenate([s[:-1] - total for s in sums])
    moves = np.concatenate([np.diff(p) for p in plug])
    jumped = np.abs(moves) > PLUG_JUMP_THRESHOLD

    edges = np.asarray(PLUG_HAZARD_EDGES)
    bins = np.searchsorted(edges, np.abs(deviation), side="right") - 1
    ticks = np.bincount(bins, minlength=len(edges))
    jumps = np.bincount(bins, weights=jumped, minlength=len(edges))
    slope = float(np.sum(moves[jumped] * deviation[jumped]) / np.sum(deviation[jumped] ** 2))
    return Plug(
        members=tuple(names),
        total=total,
        hazard_edges=PLUG_HAZARD_EDGES,
        hazard_probs=monotone_hazard(jumps, ticks),
        slope=slope,
        residual_sd=float(np.std(moves[jumped] - slope * deviation[jumped])),
    )


def monotone_hazard(events: np.ndarray, exposure: np.ndarray) -> tuple[float, ...]:
    """Per-bin event rates, forced non-decreasing in the deviation.

    Bins with no exposure take the previous bin's rate, so a deviation the data never reached still gets restored.
    """
    rates = []
    for count, ticks in zip(events.tolist(), exposure.tolist(), strict=True):
        rate = count / ticks if ticks > 0 else (rates[-1] if rates else 0.0)
        rates.append(max(rate, rates[-1]) if rates else rate)
    return tuple(rates)


def fit_basket(basket: Sequence[np.ndarray], legs: Mapping[str, Sequence[np.ndarray]]) -> Basket:
    """Integer leg weights from a regression of basket changes on leg changes; the premium is a random walk."""
    lag = BASKET_REGRESSION_LAG
    names = list(legs)
    target = np.concatenate([b[lag::lag] - b[:-lag:lag] for b in basket])
    design = np.column_stack([np.concatenate([leg[lag::lag] - leg[:-lag:lag] for leg in legs[name]]) for name in names])
    betas, *_ = np.linalg.lstsq(design, target, rcond=None)
    weights = {name: int(round(beta)) for name, beta in zip(names, betas, strict=True)}
    premiums = [b - sum(weights[name] * legs[name][day] for name in names) for day, b in enumerate(basket)]
    return Basket(legs=weights, premium_sigma=fit_random_walk(premiums).sigma)


def days_to_expiry(day: int, expiry_at_first_day: float, first_day: int, ticks: int) -> np.ndarray:
    """Days left at each tick: `expiry_at_first_day` at the open of `first_day`, falling one per day, intraday too."""
    return expiry_at_first_day - (day - first_day) - np.arange(ticks) / TICKS_PER_DAY


def implied_vol(price: np.ndarray, spot: np.ndarray, strike: float, days: np.ndarray) -> np.ndarray:
    low, high = np.full_like(price, 1e-5), np.full_like(price, IV_MAX)
    for _ in range(IV_BISECTION_STEPS):
        middle = (low + high) / 2
        too_cheap = black_scholes_call(spot, strike, days, middle) < price
        low, high = np.where(too_cheap, middle, low), np.where(too_cheap, high, middle)
    return (low + high) / 2


@dataclass(frozen=True)
class VoucherFit:
    surface: VoucherSurface
    strikes: Mapping[int, Voucher]
    residuals: Mapping[int, tuple[np.ndarray, ...]]
    sign_agreement: Mapping[int, float]
    quote_noise_sd: Mapping[int, float]


def fit_smile(
    spot: Sequence[np.ndarray], vouchers: Mapping[int, Sequence[np.ndarray]], days_left: Sequence[np.ndarray]
) -> tuple[float, float, float]:
    """IV = level_day + skew * m + curvature * m^2 over sampled ticks; returns (mean level, skew, curvature)."""
    rows, targets = [], []
    n_days = len(spot)
    sample = slice(0, None, SMILE_SAMPLE_EVERY)
    for day in range(n_days):
        s, t = spot[day][sample], days_left[day][sample]
        for strike, mids in vouchers.items():
            iv = implied_vol(mids[day][sample], s, strike, t)
            moneyness = np.log(strike / s) / np.sqrt(t)
            usable = (iv > 1e-4) & (iv < IV_MAX * 0.99)
            dummies = np.zeros((int(usable.sum()), n_days))
            dummies[:, day] = 1.0
            rows.append(np.column_stack([dummies, moneyness[usable], moneyness[usable] ** 2]))
            targets.append(iv[usable])
    coef, *_ = np.linalg.lstsq(np.vstack(rows), np.concatenate(targets), rcond=None)
    return float(np.mean(coef[:n_days])), float(coef[n_days]), float(coef[n_days + 1])


def book_noise_var(layer: Layer, extra_sd: float = 0.0) -> float:
    """Variance a quote center picks up from rounding (1/12) and two independent touch jitters."""
    jitter_var = ((layer.jitter + 1) ** 2 - 1) / 12.0
    return 1.0 / 12.0 + jitter_var / 2.0 + extra_sd**2


@dataclass(frozen=True)
class _Greeks:
    residual: np.ndarray
    vega: np.ndarray
    delta: np.ndarray


def _greeks(spot: np.ndarray, mid: np.ndarray, days: np.ndarray, strike: int, surface: VoucherSurface) -> _Greeks:
    """Mispricing against the static smile, with vega (per unit IV) and delta."""
    vol = smile_vol(surface, spot, strike, days)
    root_t = np.sqrt(days)
    d1 = (np.log(spot / strike) + 0.5 * vol**2 * days) / (vol * root_t)
    density = np.exp(-0.5 * d1**2) / math.sqrt(2.0 * math.pi)
    residual = mid - black_scholes_call(spot, strike, days, vol)
    return _Greeks(residual=residual, vega=spot * density * root_t, delta=norm_cdf(d1))


def _ar1_fit(series: Sequence[np.ndarray]) -> tuple[float, float]:
    """Stationary sd and lag-1 coefficient of a zero-mean AR(1)."""
    pooled = np.concatenate(series)
    var = max(float(np.mean(pooled**2)), 1e-12)
    lag_cov = float(np.mean(np.concatenate([x[1:] * x[:-1] for x in series])))
    return math.sqrt(var), float(np.clip(lag_cov / var, 0.0, 0.9999))


def fit_vouchers(
    spot: Sequence[np.ndarray],
    vouchers: Mapping[int, Sequence[np.ndarray]],
    days_left: Sequence[np.ndarray],
    voucher_layers: Mapping[int, Layer],
    spot_noise_var: float,
    underlying: str,
    target_days_to_expiry: float,
) -> VoucherFit:
    """Static smile, a shared IV factor, and per-strike AR(1) noise.

    Each tick, the strikes' mispricings are regressed on their vegas to read off the shared IV factor. What is
    left is per-strike noise: a white part plus an AR(1), separated by fitting the residuals' variogram (a moment
    fit at lag 1 is fragile here, as an assumed noise level slightly too high pushes phi to 1). The generator adds
    the vouchers' book noise and the underlying's quote noise (times delta^2) back on its own; any white noise
    beyond those becomes the voucher's quote noise.
    The returned `residuals` are these idiosyncratic mispricings: the voucher takers' rule is measured against them,
    because they are what reverts within the day (the shared factor drifts for thousands of ticks, so trading on
    it earns nothing, while real voucher takers' trades are followed by the mispricing correcting).
    """
    level, skew, curvature = fit_smile(spot, vouchers, days_left)
    static = VoucherSurface(0.0, level, skew, curvature, 0.0, 0.0, 0.0)
    greeks = {
        strike: [_greeks(spot[day], mid, days_left[day], strike, static) for day, mid in enumerate(mids)]
        for strike, mids in vouchers.items()
    }
    factor = [
        sum(g[d].residual * g[d].vega for g in greeks.values()) / sum(g[d].vega ** 2 for g in greeks.values())
        for d in range(len(spot))
    ]
    factor_sd, factor_phi = _ar1_fit(factor)

    strikes, residuals, agreement, quote_noise = {}, {}, {}, {}
    for strike, per_day in greeks.items():
        idiosyncratic = [g.residual - g.vega * f for g, f in zip(per_day, factor, strict=True)]
        demeaned = [x - x.mean() for x in idiosyncratic]
        fit = fit_mean_reverting(demeaned)
        phi = 1.0 - fit.kappa
        strikes[strike] = Voucher(
            underlying=underlying,
            strike=strike,
            residual_sd=fit.sigma / math.sqrt(1.0 - phi**2),
            residual_phi=phi,
        )
        residuals[strike] = tuple(demeaned)
        mean_delta_sq = float(np.mean(np.concatenate([g.delta for g in per_day]) ** 2))
        supplied = book_noise_var(voucher_layers[strike]) + mean_delta_sq * spot_noise_var
        quote_noise[strike] = math.sqrt(max(fit.noise_var - supplied, 0.0))
        measured_var = float(np.mean(np.concatenate(residuals[strike]) ** 2))
        signal_share = min(max(measured_var - fit.noise_var, 0.0) / measured_var, 1.0)
        agreement[strike] = 0.5 + math.asin(math.sqrt(signal_share)) / math.pi
    surface = VoucherSurface(
        days_to_expiry=target_days_to_expiry,
        iv_level=level,
        skew=skew,
        curvature=curvature,
        factor_start=float(factor[-1][-1]),
        factor_sd=factor_sd,
        factor_phi=factor_phi,
    )
    return VoucherFit(surface, strikes, residuals, agreement, quote_noise)
