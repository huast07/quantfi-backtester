"""Shared building blocks for case modifiers: random amounts, product selectors, event timing and shapes."""

import zlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from types import MappingProxyType

import numpy as np

from quantgen.generator import processes as proc
from quantgen.generator.params import MarketParams, ProductParams
from quantgen.generator.scenario import REGULAR_DAY, Scenario
from quantgen.generator.takers import NoiseFlow

Amount = float | tuple[float, float]
"""A fixed number, or [low, high] drawn uniformly for each seed (and each product, where a modifier says so)."""

DIFFUSIVE = (proc.RandomWalk, proc.LocalTrend, proc.MeanReverting, proc.JumpDiffusion)
GROUPS: dict[str, Callable[[ProductParams], bool]] = {
    "@all": lambda p: True,
    "@diffusive": lambda p: isinstance(p.process, DIFFUSIVE),
    "@random_walks": lambda p: isinstance(p.process, proc.RandomWalk | proc.LocalTrend),
    "@vouchers": lambda p: isinstance(p.process, proc.Voucher),
    "@plugs": lambda p: isinstance(p.process, proc.Plug),
    "@noise_flow": lambda p: isinstance(p.flow, NoiseFlow),
}


def draw(amount: Amount, rng: np.random.Generator) -> float:
    if isinstance(amount, tuple):
        low, high = amount
        return float(rng.uniform(low, high))
    return float(amount)


def select(params: MarketParams, selectors: Sequence[str]) -> tuple[str, ...]:
    """Product names from explicit names and @groups, sorted so random draws per product are reproducible."""
    names: set[str] = set()
    for selector in selectors:
        if selector in GROUPS:
            names.update(name for name, product in params.products.items() if GROUPS[selector](product))
        elif selector in params.products:
            names.add(selector)
        else:
            raise ValueError(f"unknown product or group {selector!r} (groups: {', '.join(GROUPS)})")
    return tuple(sorted(names))


def update_products(
    params: MarketParams, names: Sequence[str], change: Callable[[str, ProductParams], ProductParams]
) -> MarketParams:
    products = {name: change(name, product) if name in names else product for name, product in params.products.items()}
    return replace(params, products=MappingProxyType(products))


@dataclass(frozen=True)
class CaseContext:
    """What a modifier needs to realize itself for one seed. `event_tick` is shared by every modifier in the case,
    so a crash, its spread blow-out and its IV spike all start together."""

    case_id: str
    seed: int
    index: int
    ticks: int
    event_tick: int

    def rng(self, purpose: str) -> np.random.Generator:
        key = zlib.crc32(f"{self.case_id}:{self.index}:{purpose}".encode())
        return np.random.default_rng([self.seed, key])


def event_shape(
    ticks: int, start: int, ramp: int, hold: int = 0, recovery: float = 0.0, recovery_ticks: int = 1
) -> np.ndarray:
    """0 before `start`, rises linearly to 1 over `ramp` ticks, holds, then gives back `recovery` of the move over
    `recovery_ticks` and stays there."""
    t = np.arange(ticks, dtype=float)
    rise = np.clip((t - start + 1) / max(ramp, 1), 0.0, 1.0)
    recover_start = start + max(ramp, 1) + hold
    give_back = recovery * np.clip((t - recover_start + 1) / max(recovery_ticks, 1), 0.0, 1.0)
    return rise - give_back


def window(ticks: int, start: int, duration: int | None) -> np.ndarray:
    t = np.arange(ticks)
    end = ticks if duration is None else start + duration
    return (t >= start) & (t < end)


def random_sign(rng: np.random.Generator) -> float:
    return 1.0 if rng.random() < 0.5 else -1.0


class ParamModifier:
    """A modifier that only changes the day's parameters."""

    def apply_params(self, params: MarketParams, ctx: CaseContext) -> MarketParams:
        raise NotImplementedError

    def realize(self, params: MarketParams, ctx: CaseContext) -> Scenario:
        return REGULAR_DAY


class PathModifier:
    """A modifier that changes the day tick by tick (events, volatility profiles, liquidity windows)."""

    def apply_params(self, params: MarketParams, ctx: CaseContext) -> MarketParams:
        return params

    def realize(self, params: MarketParams, ctx: CaseContext) -> Scenario:
        raise NotImplementedError
