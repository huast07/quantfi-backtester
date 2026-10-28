"""Case modifiers that reshape volatility through time by scaling each product's innovations tick by tick."""

from dataclasses import dataclass
from types import MappingProxyType
from typing import ClassVar

import numpy as np

from quantgen.cases.context import Amount, CaseContext, PathModifier, draw, select, window
from quantgen.generator.book import markov_switch
from quantgen.generator.market import innovations
from quantgen.generator.params import MarketParams
from quantgen.generator.scenario import Scenario


def _same_scale(names: tuple[str, ...], scale: np.ndarray) -> Scenario:
    return Scenario(innovation_scale=MappingProxyType(dict.fromkeys(names, scale)))


def garch_scale(z: np.ndarray, alpha: float, beta: float) -> np.ndarray:
    """sqrt(h_t) for GARCH(1,1) with unit unconditional variance, h_t = (1-a-b) + a*e_{t-1}^2 + b*h_{t-1}."""
    omega = 1.0 - alpha - beta
    h = np.empty(z.shape[0])
    previous_h, previous_e2 = 1.0, 1.0
    for tick, shock in enumerate(z):
        previous_h = omega + alpha * previous_e2 + beta * previous_h
        h[tick] = previous_h
        previous_e2 = previous_h * shock * shock
    return np.sqrt(h)


@dataclass(frozen=True)
class Garch(PathModifier):
    """Volatility clusters: each product's variance follows GARCH(1,1) driven by its own shocks (Bollerslev, 1986).
    The unconditional variance is unchanged, so the day is as volatile on average, but unevenly."""

    KIND: ClassVar[str] = "garch"
    products: tuple[str, ...]
    alpha: float
    beta: float

    def __post_init__(self) -> None:
        if not (self.alpha >= 0 and self.beta >= 0 and self.alpha + self.beta < 1):
            raise ValueError("garch needs alpha, beta >= 0 and alpha + beta < 1")

    def realize(self, params: MarketParams, ctx: CaseContext) -> Scenario:
        z = innovations(params, ctx.seed)
        scales = {name: garch_scale(z[name], self.alpha, self.beta) for name in select(params, self.products)}
        return Scenario(innovation_scale=MappingProxyType(scales))


@dataclass(frozen=True)
class FatTails(PathModifier):
    """Student-t innovations with `dof` degrees of freedom and unit variance. One mixing draw per tick is shared by
    every product, so correlations are kept (a multivariate t)."""

    KIND: ClassVar[str] = "fat_tails"
    products: tuple[str, ...]
    dof: float

    def __post_init__(self) -> None:
        if self.dof <= 2:
            raise ValueError("fat_tails needs dof > 2 for a finite variance")

    def realize(self, params: MarketParams, ctx: CaseContext) -> Scenario:
        chi2 = ctx.rng("mixing").chisquare(self.dof, ctx.ticks)
        return _same_scale(select(params, self.products), np.sqrt((self.dof - 2.0) / chi2))


@dataclass(frozen=True)
class VolRegimes(PathModifier):
    """A hidden calm/turbulent Markov chain shared by the selected products (Hamilton, 1989). Turbulent volatility
    is `turbulent_ratio` times calm, and both are set so the average variance is unchanged."""

    KIND: ClassVar[str] = "vol_regimes"
    products: tuple[str, ...]
    turbulent_ratio: float
    start_prob: float
    stay_prob: float

    def realize(self, params: MarketParams, ctx: CaseContext) -> Scenario:
        turbulent = markov_switch(ctx.rng("regime"), ctx.ticks, self.start_prob, self.stay_prob)
        share = self.start_prob / (1.0 - self.stay_prob + self.start_prob)
        calm = 1.0 / np.sqrt(1.0 - share + share * self.turbulent_ratio**2)
        return _same_scale(select(params, self.products), np.where(turbulent, calm * self.turbulent_ratio, calm))


def u_shape(ticks: int, amplitude: float) -> np.ndarray:
    """Mean-one intraday profile, highest at the open and close: 1 + a * ((2x - 1)^2 - 1/3)."""
    x = np.arange(ticks) / max(ticks - 1, 1)
    return 1.0 + amplitude * ((2.0 * x - 1.0) ** 2 - 1.0 / 3.0)


@dataclass(frozen=True)
class IntradayProfile(PathModifier):
    """U-shaped intraday variance (and taker arrivals when `flow`), with the daily average unchanged
    (Admati & Pfleiderer, 1988; Andersen & Bollerslev, 1997)."""

    KIND: ClassVar[str] = "intraday_profile"
    products: tuple[str, ...]
    amplitude: float
    flow: bool = True

    def __post_init__(self) -> None:
        if not 0 <= self.amplitude < 1.5:
            raise ValueError("intraday_profile amplitude must be in [0, 1.5) so the profile stays positive")

    def realize(self, params: MarketParams, ctx: CaseContext) -> Scenario:
        names = select(params, self.products)
        variance = u_shape(ctx.ticks, self.amplitude)
        flow = MappingProxyType(dict.fromkeys(names, variance)) if self.flow else MappingProxyType({})
        return Scenario(innovation_scale=MappingProxyType(dict.fromkeys(names, np.sqrt(variance))), flow_scale=flow)


@dataclass(frozen=True)
class VolWindow(PathModifier):
    """Volatility is `factor` times normal for `duration_ticks`, starting `delay_ticks` after the event."""

    KIND: ClassVar[str] = "vol_window"
    products: tuple[str, ...]
    factor: Amount
    duration_ticks: Amount
    delay_ticks: Amount = 0.0

    def realize(self, params: MarketParams, ctx: CaseContext) -> Scenario:
        rng = ctx.rng("window")
        factor = draw(self.factor, rng)
        inside = window(
            ctx.ticks, ctx.event_tick + int(draw(self.delay_ticks, rng)), int(draw(self.duration_ticks, rng))
        )
        return _same_scale(select(params, self.products), np.where(inside, factor, 1.0))
