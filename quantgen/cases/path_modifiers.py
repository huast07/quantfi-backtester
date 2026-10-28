"""Case modifiers that move fair values during the day: shocks, trend changes, the pearl total and the IV level."""

from dataclasses import dataclass
from types import MappingProxyType
from typing import ClassVar

import numpy as np

from quantgen.cases.context import (
    Amount,
    CaseContext,
    PathModifier,
    draw,
    event_shape,
    random_sign,
    select,
)
from quantgen.generator.params import MarketParams
from quantgen.generator.processes import TICKS_PER_DAY
from quantgen.generator.scenario import Scenario

DIRECTIONS = {"down": -1.0, "up": 1.0}
RANDOM = "random"


def _direction(direction: str, rng: np.random.Generator) -> float:
    return random_sign(rng) if direction == RANDOM else DIRECTIONS[direction]


def _check_direction(direction: str) -> None:
    if direction not in (*DIRECTIONS, RANDOM):
        raise ValueError(f"direction must be one of {', '.join((*DIRECTIONS, RANDOM))}, got {direction!r}")


@dataclass(frozen=True)
class Shock(PathModifier):
    """Move fair values from the case's event time: ramp in, hold, then give back `recovery` of the move.

    `size` is a fraction of each product's opening price when `relative`, otherwise price units. `pick` limits the
    shock to that many randomly chosen products (a flash crash hits one product, a black swan hits all of them).
    """

    KIND: ClassVar[str] = "shock"
    products: tuple[str, ...]
    size: Amount
    direction: str = "down"
    relative: bool = True
    per_product_size: bool = False
    delay_ticks: Amount = 0.0
    ramp_ticks: Amount = 1.0
    hold_ticks: Amount = 0.0
    recovery: Amount = 0.0
    recovery_ticks: Amount = 1.0
    pick: int | None = None

    def __post_init__(self) -> None:
        _check_direction(self.direction)

    def realize(self, params: MarketParams, ctx: CaseContext) -> Scenario:
        rng = ctx.rng("shock")
        names = select(params, self.products)
        if self.pick is not None:
            names = tuple(sorted(rng.choice(names, size=min(self.pick, len(names)), replace=False).tolist()))
        sign = _direction(self.direction, rng)
        shape = event_shape(
            ctx.ticks,
            ctx.event_tick + int(draw(self.delay_ticks, rng)),
            int(draw(self.ramp_ticks, rng)),
            int(draw(self.hold_ticks, rng)),
            draw(self.recovery, rng),
            int(draw(self.recovery_ticks, rng)),
        )
        size = draw(self.size, rng)
        shifts = {}
        for name in names:
            product_size = draw(self.size, rng) if self.per_product_size else size
            scale = params.products[name].start if self.relative else 1.0
            shifts[name] = sign * product_size * scale * shape
        return Scenario(fair_shift=MappingProxyType(shifts))


@dataclass(frozen=True)
class TrendReversal(PathModifier):
    """Each selected product trends at `per_day` (random direction each) until the event, then reverses at the
    same speed (a Hamilton-style regime flip)."""

    KIND: ClassVar[str] = "trend_reversal"
    products: tuple[str, ...]
    per_day: Amount

    def realize(self, params: MarketParams, ctx: CaseContext) -> Scenario:
        rng = ctx.rng("trend")
        t = np.arange(ctx.ticks, dtype=float)
        tent = np.where(t < ctx.event_tick, t, 2.0 * ctx.event_tick - t)
        shifts = {
            name: random_sign(rng) * draw(self.per_day, rng) / TICKS_PER_DAY * tent
            for name in select(params, self.products)
        }
        return Scenario(fair_shift=MappingProxyType(shifts))


@dataclass(frozen=True)
class DriftChange(PathModifier):
    """From the event on, the selected products drift by an extra `per_day` price units (negative = down)."""

    KIND: ClassVar[str] = "drift_change"
    products: tuple[str, ...]
    per_day: Amount

    def realize(self, params: MarketParams, ctx: CaseContext) -> Scenario:
        rng = ctx.rng("drift")
        elapsed = np.maximum(np.arange(ctx.ticks) - ctx.event_tick, 0)
        shifts = {name: draw(self.per_day, rng) / TICKS_PER_DAY * elapsed for name in select(params, self.products)}
        return Scenario(fair_shift=MappingProxyType(shifts))


@dataclass(frozen=True)
class PlugTotalShift(PathModifier):
    """The total a plug restores (the five-pearl 50,000) moves by `size` at the event, over `ramp_ticks`."""

    KIND: ClassVar[str] = "plug_total_shift"
    products: tuple[str, ...]
    size: Amount
    direction: str = RANDOM
    ramp_ticks: Amount = 1.0

    def __post_init__(self) -> None:
        _check_direction(self.direction)

    def realize(self, params: MarketParams, ctx: CaseContext) -> Scenario:
        rng = ctx.rng("total")
        move = _direction(self.direction, rng) * draw(self.size, rng)
        shape = event_shape(ctx.ticks, ctx.event_tick, int(draw(self.ramp_ticks, rng)))
        return Scenario(plug_shift=MappingProxyType({name: move * shape for name in select(params, self.products)}))


@dataclass(frozen=True)
class IvShock(PathModifier):
    """The voucher IV level (per sqrt-day) jumps by `size` at the event and then gives back `recovery` of it."""

    KIND: ClassVar[str] = "iv_shock"
    size: Amount
    delay_ticks: Amount = 0.0
    ramp_ticks: Amount = 1.0
    hold_ticks: Amount = 0.0
    recovery: Amount = 0.0
    recovery_ticks: Amount = 1.0

    def realize(self, params: MarketParams, ctx: CaseContext) -> Scenario:
        rng = ctx.rng("iv")
        shape = event_shape(
            ctx.ticks,
            ctx.event_tick + int(draw(self.delay_ticks, rng)),
            int(draw(self.ramp_ticks, rng)),
            int(draw(self.hold_ticks, rng)),
            draw(self.recovery, rng),
            int(draw(self.recovery_ticks, rng)),
        )
        return Scenario(iv_shift=draw(self.size, rng) * shape)
