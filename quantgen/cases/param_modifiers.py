"""Case modifiers that change the day's parameters: volatility, flow, book, drift, jumps, steps, surface, links."""

from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import ClassVar

import numpy as np

from quantgen.calibration.fit_processes import nearest_correlation
from quantgen.cases.context import Amount, CaseContext, ParamModifier, draw, random_sign, select, update_products
from quantgen.generator import processes as proc
from quantgen.generator.book import Layer
from quantgen.generator.params import MarketParams, ProductParams
from quantgen.generator.processes import TICKS_PER_DAY
from quantgen.generator.takers import ChaseFlow, Flow, IvRuleFlow, NoiseFlow

MIN_BUY_PROB, MAX_BUY_PROB = 0.0, 1.0


def scale_process_volatility(process: proc.Process, factor: float) -> proc.Process:
    match process:
        case proc.RandomWalk() | proc.MeanReverting():
            return replace(process, sigma=process.sigma * factor)
        case proc.LocalTrend():
            return replace(process, sigma=process.sigma * factor, trend_sd=process.trend_sd * factor)
        case proc.JumpDiffusion():
            return replace(process, diffusion=scale_process_volatility(process.diffusion, factor))
        case proc.Basket():
            return replace(process, premium_sigma=process.premium_sigma * factor)
        case proc.Plug():
            return replace(process, residual_sd=process.residual_sd * factor)
    return process


def scale_flow_rate(flow: Flow, factor: float) -> Flow:
    match flow:
        case NoiseFlow() | IvRuleFlow():
            return replace(flow, rate=min(flow.rate * factor, 1.0))
        case ChaseFlow():
            order_prob = tuple(min(p * factor, 1.0) for p in flow.order_prob)
            return replace(flow, base_rate=min(flow.base_rate * factor, 1.0), order_prob=order_prob)
    return flow


@dataclass(frozen=True)
class ScaleVolatility(ParamModifier):
    """Multiply each selected product's volatility by `factor` (drawn per product when a range)."""

    KIND: ClassVar[str] = "scale_volatility"
    products: tuple[str, ...]
    factor: Amount

    def apply_params(self, params: MarketParams, ctx: CaseContext) -> MarketParams:
        names = select(params, self.products)
        rng = ctx.rng("factor")
        factors = {name: draw(self.factor, rng) for name in names}
        return update_products(
            params, names, lambda n, p: replace(p, process=scale_process_volatility(p.process, factors[n]))
        )


@dataclass(frozen=True)
class ScaleFlow(ParamModifier):
    """Multiply each selected product's taker arrival rate by `factor` (drawn per product when a range)."""

    KIND: ClassVar[str] = "scale_flow"
    products: tuple[str, ...]
    factor: Amount

    def apply_params(self, params: MarketParams, ctx: CaseContext) -> MarketParams:
        names = select(params, self.products)
        rng = ctx.rng("factor")
        factors = {name: draw(self.factor, rng) for name in names}
        return update_products(params, names, lambda n, p: replace(p, flow=scale_flow_rate(p.flow, factors[n])))


@dataclass(frozen=True)
class SetNoiseFlow(ParamModifier):
    """Set noise takers' buy share (on a random side per product when `random_side`) and arrival clustering."""

    KIND: ClassVar[str] = "set_noise_flow"
    products: tuple[str, ...]
    buy_prob: Amount | None = None
    random_side: bool = False
    cluster_mean: Amount | None = None

    def apply_params(self, params: MarketParams, ctx: CaseContext) -> MarketParams:
        names = select(params, self.products)
        rng = ctx.rng("flow")

        def change(name: str, product: ProductParams) -> ProductParams:
            if not isinstance(product.flow, NoiseFlow):
                raise ValueError(f"{name}: {self.KIND} needs noise takers")
            flow = product.flow
            if self.buy_prob is not None:
                buy = draw(self.buy_prob, rng)
                buy = 1.0 - buy if self.random_side and rng.random() < 0.5 else buy
                flow = replace(flow, buy_prob=float(np.clip(buy, MIN_BUY_PROB, MAX_BUY_PROB)))
            if self.cluster_mean is not None:
                flow = replace(flow, cluster_mean=max(draw(self.cluster_mean, rng), 1.0))
            return replace(product, flow=flow)

        return update_products(params, names, change)


@dataclass(frozen=True)
class ScaleBook(ParamModifier):
    """Scale quoted volumes and push every quote layer out by `extra_half_width` ticks (rounded to whole ticks)."""

    KIND: ClassVar[str] = "scale_book"
    products: tuple[str, ...]
    volume_factor: Amount = 1.0
    extra_half_width: Amount = 0.0

    def apply_params(self, params: MarketParams, ctx: CaseContext) -> MarketParams:
        names = select(params, self.products)
        rng = ctx.rng("book")
        volume_factor, extra = draw(self.volume_factor, rng), float(round(draw(self.extra_half_width, rng)))

        def layer(base: Layer) -> Layer:
            volumes = tuple(max(int(round(v * volume_factor)), 1) for v in base.volumes)
            return replace(base, half_width=base.half_width + extra, volumes=volumes)

        def change(_: str, product: ProductParams) -> ProductParams:
            book = product.book
            inner = replace(book.inner, layer=layer(book.inner.layer)) if book.inner else None
            return replace(product, book=replace(book, layers=tuple(layer(x) for x in book.layers), inner=inner))

        return update_products(params, names, change)


@dataclass(frozen=True)
class SetDrift(ParamModifier):
    """Give random-walk products a drift of `per_day` price units (with a random sign per product if asked)."""

    KIND: ClassVar[str] = "set_drift"
    products: tuple[str, ...]
    per_day: Amount
    random_sign: bool = False

    def apply_params(self, params: MarketParams, ctx: CaseContext) -> MarketParams:
        names = select(params, self.products)
        rng = ctx.rng("drift")

        def change(name: str, product: ProductParams) -> ProductParams:
            if not isinstance(product.process, proc.RandomWalk | proc.LocalTrend):
                raise ValueError(f"{name}: {self.KIND} needs a random-walk product")
            sign = random_sign(rng) if self.random_sign else 1.0
            return replace(
                product, process=replace(product.process, drift=sign * draw(self.per_day, rng) / TICKS_PER_DAY)
            )

        return update_products(params, names, change)


def _scaled_response(response: proc.JumpResponse, size: float, factor: float) -> proc.JumpResponse:
    """Jumps `size` times bigger get a response `size` times bigger (the slope is per unit of excess size)."""
    return replace(
        response,
        drift=tuple(d * size * factor for d in response.drift),
        size_slope=tuple(s * factor for s in response.size_slope),
        reference_size=response.reference_size * size,
    )


@dataclass(frozen=True)
class ScaleJumps(ParamModifier):
    """Scale jump rate and size (the post-jump response scales with the size, keeping its shape).
    `direction_concentration` replaces the Beta(c, c) concentration of the day's
    up-probability: small c gives one-directional days, large c gives days of mixed up and down jumps.
    `response_factor` scales the post-jump response: 0 makes every jump simply stick."""

    KIND: ClassVar[str] = "scale_jumps"
    products: tuple[str, ...]
    rate_factor: Amount = 1.0
    size_factor: Amount = 1.0
    direction_concentration: Amount | None = None
    response_factor: Amount = 1.0

    def apply_params(self, params: MarketParams, ctx: CaseContext) -> MarketParams:
        names = select(params, self.products)
        rng = ctx.rng("jumps")
        rate, size = draw(self.rate_factor, rng), draw(self.size_factor, rng)

        def change(name: str, product: ProductParams) -> ProductParams:
            process = product.process
            if not isinstance(process, proc.JumpDiffusion):
                raise ValueError(f"{name}: {self.KIND} needs a jump-diffusion product")
            sizes = tuple(s * size for s in process.jump_sizes)
            jumps = replace(process, jumps_per_day=process.jumps_per_day * rate, jump_sizes=sizes)
            if self.direction_concentration is not None:
                jumps = replace(jumps, direction_concentration=draw(self.direction_concentration, rng))
            if process.response is not None:
                factor = draw(self.response_factor, rng)
                jumps = replace(jumps, response=_scaled_response(process.response, size, factor))
            return replace(product, process=jumps)

        return update_products(params, names, change)


@dataclass(frozen=True)
class SetSteps(ParamModifier):
    """Change a stepping product's daily step counts and scale its step sizes (-1 reverses the direction)."""

    KIND: ClassVar[str] = "set_steps"
    products: tuple[str, ...]
    daily_counts: tuple[int, ...] | None = None
    size_factor: float = 1.0

    def apply_params(self, params: MarketParams, ctx: CaseContext) -> MarketParams:
        def change(name: str, product: ProductParams) -> ProductParams:
            process = product.process
            if not isinstance(process, proc.Steps):
                raise ValueError(f"{name}: {self.KIND} needs a stepping product")
            counts = process.daily_counts if self.daily_counts is None else self.daily_counts
            sizes = tuple(s * self.size_factor for s in process.step_sizes)
            return replace(product, process=replace(process, daily_counts=counts, step_sizes=sizes))

        return update_products(params, select(params, self.products), change)


@dataclass(frozen=True)
class ScaleMeanReversion(ParamModifier):
    KIND: ClassVar[str] = "scale_mean_reversion"
    products: tuple[str, ...]
    kappa_factor: Amount

    def apply_params(self, params: MarketParams, ctx: CaseContext) -> MarketParams:
        names = select(params, self.products)
        rng = ctx.rng("kappa")

        def change(name: str, product: ProductParams) -> ProductParams:
            process = product.process
            if not isinstance(process, proc.MeanReverting):
                raise ValueError(f"{name}: {self.KIND} needs a mean-reverting product")
            return replace(product, process=replace(process, kappa=process.kappa * draw(self.kappa_factor, rng)))

        return update_products(params, names, change)


@dataclass(frozen=True)
class ScalePlug(ParamModifier):
    """Make a plug restore its total less often (`hazard_factor`) and less fully (`slope_factor`)."""

    KIND: ClassVar[str] = "scale_plug"
    products: tuple[str, ...]
    hazard_factor: Amount = 1.0
    slope_factor: Amount = 1.0

    def apply_params(self, params: MarketParams, ctx: CaseContext) -> MarketParams:
        names = select(params, self.products)
        rng = ctx.rng("plug")
        hazard, slope = draw(self.hazard_factor, rng), draw(self.slope_factor, rng)

        def change(name: str, product: ProductParams) -> ProductParams:
            process = product.process
            if not isinstance(process, proc.Plug):
                raise ValueError(f"{name}: {self.KIND} needs a plug product")
            probs = tuple(min(p * hazard, 1.0) for p in process.hazard_probs)
            return replace(product, process=replace(process, hazard_probs=probs, slope=process.slope * slope))

        return update_products(params, names, change)


@dataclass(frozen=True)
class AdjustSurface(ParamModifier):
    """Reshape the voucher IV surface. `realised_iv` sets the IV level to the underlying's realised volatility,
    removing the variance risk premium (Carr & Wu, 2009)."""

    KIND: ClassVar[str] = "adjust_surface"
    iv_factor: Amount = 1.0
    iv_shift: Amount = 0.0
    skew_factor: Amount = 1.0
    curvature_factor: Amount = 1.0
    realised_iv: bool = False
    sticky_strike: bool | None = None

    def apply_params(self, params: MarketParams, ctx: CaseContext) -> MarketParams:
        rng = ctx.rng("surface")
        surface = params.voucher_surface
        level = realised_daily_vol(params) if self.realised_iv else surface.iv_level
        surface = replace(
            surface,
            iv_level=level * draw(self.iv_factor, rng) + draw(self.iv_shift, rng),
            skew=surface.skew * draw(self.skew_factor, rng),
            curvature=surface.curvature * draw(self.curvature_factor, rng),
            factor_start=0.0 if self.realised_iv else surface.factor_start,
            sticky_strike=surface.sticky_strike if self.sticky_strike is None else self.sticky_strike,
        )
        return replace(params, voucher_surface=surface)


def realised_daily_vol(params: MarketParams) -> float:
    """Daily volatility (as a fraction) of the vouchers' underlying, from its tick sigma."""
    voucher = next(p.process for p in params.products.values() if isinstance(p.process, proc.Voucher))
    underlying = params.products[voucher.underlying]
    if not isinstance(underlying.process, proc.RandomWalk):
        raise ValueError(f"{voucher.underlying}: realised IV needs a random-walk underlying")
    return underlying.process.sigma * np.sqrt(TICKS_PER_DAY) / underlying.start


@dataclass(frozen=True)
class ChangeCorrelation(ParamModifier):
    """Flip the sign of, or blend towards `toward`, the correlations among the selected products."""

    KIND: ClassVar[str] = "change_correlation"
    products: tuple[str, ...]
    flip: bool = False
    toward: float | None = None
    weight: Amount = 1.0

    def apply_params(self, params: MarketParams, ctx: CaseContext) -> MarketParams:
        group = params.correlation.products
        chosen = [group.index(name) for name in select(params, self.products) if name in group]
        matrix = np.array(params.correlation.matrix)
        weight = draw(self.weight, ctx.rng("weight"))
        for i in chosen:
            for j in chosen:
                if i == j:
                    continue
                target = -matrix[i, j] if self.flip else self.toward if self.toward is not None else matrix[i, j]
                matrix[i, j] = (1.0 - weight) * matrix[i, j] + weight * target
        fixed = nearest_correlation(matrix)
        correlation = replace(params.correlation, matrix=tuple(tuple(float(v) for v in row) for row in fixed))
        return replace(params, correlation=correlation)


@dataclass(frozen=True)
class OpeningGap(ParamModifier):
    """Open the selected products `fraction` away from the previous close, in a random direction each.
    Baskets keep their premium, so they gap with their legs."""

    KIND: ClassVar[str] = "opening_gap"
    products: tuple[str, ...]
    fraction: Amount

    def apply_params(self, params: MarketParams, ctx: CaseContext) -> MarketParams:
        names = select(params, self.products)
        rng = ctx.rng("gap")
        moves = {name: random_sign(rng) * draw(self.fraction, rng) * params.products[name].start for name in names}
        starts = {name: params.products[name].start + move for name, move in moves.items()}
        for name, product in params.products.items():
            if isinstance(product.process, proc.Basket) and name not in names:
                legs_move = sum(weight * moves.get(leg, 0.0) for leg, weight in product.process.legs.items())
                starts[name] = product.start + legs_move
        products = {name: replace(p, start=starts.get(name, p.start)) for name, p in params.products.items()}
        return replace(params, products=MappingProxyType(products))
