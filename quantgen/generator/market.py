"""Generate one synthetic trading day from calibrated parameters: fair values -> books -> taker tape.

Generation is deterministic in (params, seed). Each product draws from its own random streams, keyed by the product
name, so changing one product's parameters (as a case does) leaves every other product's path unchanged.
"""

import zlib
from dataclasses import dataclass, replace
from types import MappingProxyType

import numpy as np

from quantgen.generator import processes as proc
from quantgen.generator.book import Book, build_book
from quantgen.generator.params import MarketParams, ProductParams
from quantgen.generator.processes import FairValue
from quantgen.generator.scenario import REGULAR_DAY, Informed, Scenario
from quantgen.generator.takers import (
    ChaseExpectation,
    ChaseFlow,
    IvRuleFlow,
    NoiseFlow,
    Orders,
    Tape,
    chase_book_adjustment,
    chase_orders,
    expect_chase,
    impact_path,
    iv_rule_tape,
    noise_tape,
    sweep,
)
from quantgen.market_day import MarketDay, ProductDay

PROCESS, QUOTE_NOISE, BOOK, FLOW, WIDEN, INNOVATION = range(6)
CORRELATION_KEY = "__correlation__"
IV_FACTOR_KEY = "__iv_factor__"


def stream(seed: int, product: str, purpose: int) -> np.random.Generator:
    return np.random.default_rng([seed, zlib.crc32(product.encode()), purpose])


def innovations(params: MarketParams, seed: int) -> dict[str, np.ndarray]:
    """Standard-normal innovations per product, correlated within params.correlation."""
    group = params.correlation.products
    out: dict[str, np.ndarray] = {}
    if group:
        chol = np.linalg.cholesky(np.asarray(params.correlation.matrix))
        draws = stream(seed, CORRELATION_KEY, INNOVATION).standard_normal((params.ticks, len(group))) @ chol.T
        out.update({name: draws[:, i] for i, name in enumerate(group)})
    for name in params.products:
        if name not in out:
            out[name] = stream(seed, name, INNOVATION).standard_normal(params.ticks)
    return out


class _FairValues:
    """Resolves fair values in dependency order (baskets need legs, vouchers need the underlying).

    Vouchers are priced off the underlying's fair value, not its quotes: real voucher mids react to only part of the
    underlying's tick-level quote noise (their beta to it is attenuated at one tick and recovers within ~20).
    """

    def __init__(self, params: MarketParams, seed: int, scenario: Scenario) -> None:
        self.params = params
        self.seed = seed
        self.scenario = scenario
        z = innovations(params, seed)
        self.z = {
            name: z[name] * scenario.innovation_scale[name] if name in scenario.innovation_scale else z[name]
            for name in z
        }
        self.done: dict[str, FairValue] = {}
        self._iv_factor: np.ndarray | None = None

    def iv_factor(self) -> np.ndarray:
        if self._iv_factor is None:
            rng = stream(self.seed, IV_FACTOR_KEY, PROCESS)
            factor = proc.iv_factor(self.params.voucher_surface, self.params.ticks, rng)
            self._iv_factor = factor if self.scenario.iv_shift is None else factor + self.scenario.iv_shift
        return self._iv_factor

    def get(self, name: str) -> FairValue:
        if name not in self.done:
            fair = self._simulate(name, self.params.products[name])
            shift = self.scenario.fair_shift.get(name)
            self.done[name] = fair if shift is None else replace(fair, path=fair.path + shift)
        return self.done[name]

    def _simulate(self, name: str, product: ProductParams) -> FairValue:
        process, start, z = product.process, product.start, self.z[name]
        rng = stream(self.seed, name, PROCESS)
        match process:
            case proc.Constant():
                return proc.constant(process, self.params.ticks)
            case proc.RandomWalk():
                return proc.random_walk(process, start, z)
            case proc.MeanReverting():
                return proc.mean_reverting(process, start, z)
            case proc.LocalTrend():
                return proc.local_trend(process, start, z)
            case proc.Steps():
                return proc.steps(process, start, self.params.ticks, rng)
            case proc.JumpDiffusion():
                return proc.jump_diffusion(process, start, z, rng)
            case proc.Basket():
                legs = {leg: self.get(leg).path for leg in process.legs}
                starts = {leg: self.params.products[leg].start for leg in process.legs}
                return proc.basket(process, start, legs, starts, z)
            case proc.Voucher():
                spot = self.get(process.underlying).path
                return proc.voucher(process, self.params.voucher_surface, spot, self.iv_factor(), rng)
        raise ValueError(f"{name}: {type(process).__name__} must be generated after the books")


def _center(name: str, product: ProductParams, fair: FairValue, seed: int) -> np.ndarray:
    if product.quote_noise_sd <= 0:
        return fair.path
    return fair.path + product.quote_noise_sd * stream(seed, name, QUOTE_NOISE).standard_normal(fair.path.shape[0])


@dataclass(frozen=True)
class _Chase:
    orders: Orders
    expectation: ChaseExpectation


def _chase(name: str, flow: ChaseFlow, fair: FairValue, seed: int, scenario: Scenario) -> _Chase:
    ticks = fair.path.shape[0]
    flow_jumps = np.maximum(fair.jump_ticks - scenario.chase_lead.get(name, 0), 0)
    intensity = scenario.flow_scale.get(name)
    orders = chase_orders(flow, ticks, flow_jumps, fair.jump_signs, stream(seed, name, FLOW), intensity)
    return _Chase(orders, expect_chase(flow, ticks, flow_jumps, fair.jump_signs, intensity))


def _book(
    name: str, product: ProductParams, fair: FairValue, seed: int, scenario: Scenario, chase: _Chase | None = None
) -> Book:
    center = _center(name, product, fair, seed)
    rng = stream(seed, name, BOOK)
    ticks = fair.path.shape[0]
    widen = scenario.widen.get(name)
    scale = scenario.volume_scale.get(name)
    drop = scenario.level_drop.get(name)
    if isinstance(product.flow, ChaseFlow):
        if chase is not None:
            center = center + impact_path(product.flow, chase.orders, chase.expectation)
        adjust = chase_book_adjustment(product.flow, ticks, fair.jump_ticks, fair.jump_signs, stream(seed, name, WIDEN))
        widen = adjust.widen if widen is None else adjust.widen + widen
        bid_scale = adjust.bid_scale if scale is None else adjust.bid_scale * scale
        ask_scale = adjust.ask_scale if scale is None else adjust.ask_scale * scale
        return build_book(center, product.book, rng, widen, bid_scale, ask_scale, drop)
    return build_book(center, product.book, rng, widen, scale, scale, drop)


def informed_buy_prob(base: float | np.ndarray, fair: np.ndarray, informed: Informed) -> np.ndarray:
    """Buy probability when `informed.share` of takers trade on the move over the next `informed.horizon` ticks."""
    ticks = fair.shape[0]
    ahead = fair[np.minimum(np.arange(ticks) + informed.horizon, ticks - 1)] - fair
    knows_up = np.where(ahead > 0, 1.0, np.where(ahead < 0, 0.0, 0.5))
    return (1.0 - informed.share) * base + informed.share * knows_up


def _tape(
    name: str,
    product: ProductParams,
    fair: FairValue,
    book: Book,
    seed: int,
    scenario: Scenario,
    chase: _Chase | None = None,
) -> Tape:
    rng = stream(seed, name, FLOW)
    intensity = scenario.flow_scale.get(name)
    match product.flow:
        case NoiseFlow():
            buy_prob = scenario.buy_prob.get(name)
            if name in scenario.informed:
                base = product.flow.buy_prob if buy_prob is None else buy_prob
                buy_prob = informed_buy_prob(base, fair.path, scenario.informed[name])
            return noise_tape(product.flow, book, rng, intensity, buy_prob)
        case IvRuleFlow():
            residual = fair.residual if fair.residual is not None else np.zeros(fair.path.shape[0])
            return iv_rule_tape(product.flow, book, residual, rng, intensity)
        case ChaseFlow():
            orders = (chase or _chase(name, product.flow, fair, seed, scenario)).orders
            return sweep(book, orders.ticks, orders.sides, orders.sizes)
    raise ValueError(f"{name}: unknown flow {type(product.flow).__name__}")


def _product_day(book: Book, tape: Tape) -> ProductDay:
    return ProductDay(
        bid_prices=book.bid_prices,
        bid_volumes=book.bid_volumes,
        ask_prices=book.ask_prices,
        ask_volumes=book.ask_volumes,
        trade_ticks=tape.ticks,
        trade_prices=tape.prices,
        trade_quantities=tape.quantities,
    )


def _mid(book: Book) -> np.ndarray:
    return (book.bid_prices[:, 0] + book.ask_prices[:, 0]) / 2


def _absorb_steps(params: MarketParams, fair: dict[str, FairValue]) -> dict[str, FairValue]:
    """Move each step's absorbing products against it, in their shares."""
    adjusted = dict(fair)
    for name, product in params.products.items():
        if isinstance(product.process, proc.Steps) and name in fair:
            moved = fair[name].path - product.start
            for absorber, share in product.process.absorbers.items():
                adjusted[absorber] = replace(adjusted[absorber], path=adjusted[absorber].path - share * moved)
    return adjusted


def generate_day(params: MarketParams, seed: int, scenario: Scenario = REGULAR_DAY) -> MarketDay:
    fair_values = _FairValues(params, seed, scenario)
    plugs = {name: p.process for name, p in params.products.items() if isinstance(p.process, proc.Plug)}
    fair = _absorb_steps(params, {name: fair_values.get(name) for name in params.products if name not in plugs})
    chases = {
        name: _chase(name, product.flow, fair[name], seed, scenario)
        for name, product in params.products.items()
        if isinstance(product.flow, ChaseFlow) and name in fair
    }
    books = {name: _book(name, params.products[name], fair[name], seed, scenario, chases.get(name)) for name in fair}

    for name, plug in plugs.items():
        member_mids = sum(_mid(books[member]) for member in plug.members)
        if name in scenario.plug_shift:
            member_mids = member_mids - scenario.plug_shift[name]
        fair[name] = proc.plug(plug, params.products[name].start, member_mids, stream(seed, name, PROCESS))
        books[name] = _book(name, params.products[name], fair[name], seed, scenario)

    days = {
        name: _product_day(
            books[name], _tape(name, params.products[name], fair[name], books[name], seed, scenario, chases.get(name))
        )
        for name in sorted(params.products)
    }
    return MarketDay(day=params.day, products=MappingProxyType(days))
