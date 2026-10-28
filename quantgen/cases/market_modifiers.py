"""Case modifiers for the market maker's book and the takers' behaviour."""

from dataclasses import dataclass
from types import MappingProxyType
from typing import ClassVar

import numpy as np

from quantgen.cases.context import Amount, CaseContext, PathModifier, draw, select, window
from quantgen.generator.params import MarketParams
from quantgen.generator.scenario import Informed, Scenario
from quantgen.generator.takers import ChaseFlow, NoiseFlow


@dataclass(frozen=True)
class LiquidityWindow(PathModifier):
    """For a window after the event the market maker widens (`widen` ticks per side), shows `volume_factor` of its
    usual size, pulls each outer level with probability `level_drop`, and takers arrive `flow_factor` as often.
    `duration_ticks` omitted means until the close."""

    KIND: ClassVar[str] = "liquidity_window"
    products: tuple[str, ...]
    widen: Amount = 0.0
    volume_factor: Amount = 1.0
    level_drop: Amount = 0.0
    flow_factor: Amount = 1.0
    delay_ticks: Amount = 0.0
    duration_ticks: Amount | None = None

    def realize(self, params: MarketParams, ctx: CaseContext) -> Scenario:
        rng = ctx.rng("liquidity")
        start = ctx.event_tick + int(draw(self.delay_ticks, rng))
        duration = None if self.duration_ticks is None else int(draw(self.duration_ticks, rng))
        inside = window(ctx.ticks, start, duration)
        names = select(params, self.products)

        def profile(amount: Amount, outside: float) -> MappingProxyType:
            values = np.where(inside, draw(amount, rng), outside)
            return MappingProxyType(dict.fromkeys(names, values))

        return Scenario(
            widen=profile(self.widen, 0.0),
            volume_scale=profile(self.volume_factor, 1.0),
            level_drop=profile(self.level_drop, 0.0),
            flow_scale=profile(self.flow_factor, 1.0),
        )


@dataclass(frozen=True)
class InformedFlow(PathModifier):
    """`share` of the noise takers trade in the direction of the next `horizon_ticks` move: toxic flow for anyone
    quoting passively (Kyle, 1985; Glosten & Milgrom, 1985)."""

    KIND: ClassVar[str] = "informed_flow"
    products: tuple[str, ...]
    share: Amount
    horizon_ticks: int

    def realize(self, params: MarketParams, ctx: CaseContext) -> Scenario:
        rng = ctx.rng("informed")
        names = [name for name in select(params, self.products) if isinstance(params.products[name].flow, NoiseFlow)]
        informed = {name: Informed(share=draw(self.share, rng), horizon=self.horizon_ticks) for name in names}
        return Scenario(informed=MappingProxyType(informed))


@dataclass(frozen=True)
class ChaseLead(PathModifier):
    """Jump chasers start `lead_ticks` before each jump instead of after it: someone knows the jump is coming."""

    KIND: ClassVar[str] = "chase_lead"
    products: tuple[str, ...]
    lead_ticks: int

    def realize(self, params: MarketParams, ctx: CaseContext) -> Scenario:
        names = [name for name in select(params, self.products) if isinstance(params.products[name].flow, ChaseFlow)]
        return Scenario(chase_lead=MappingProxyType(dict.fromkeys(names, self.lead_ticks)))
