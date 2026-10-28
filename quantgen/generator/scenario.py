"""Per-tick modifications a market case makes to an otherwise regular day.

A scenario is plain data: arrays keyed by product, already realized for one seed. The generator applies it at fixed
points (innovations, fair values, books, taker flow), so an empty scenario reproduces the regular day exactly.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

import numpy as np


@dataclass(frozen=True)
class Informed:
    """A share of a product's takers trade in the direction of the fair-value move over the next `horizon` ticks."""

    share: float
    horizon: int


def _empty() -> Mapping[str, Any]:
    return MappingProxyType({})


@dataclass(frozen=True)
class Scenario:
    innovation_scale: Mapping[str, np.ndarray] = field(default_factory=_empty)
    fair_shift: Mapping[str, np.ndarray] = field(default_factory=_empty)
    plug_shift: Mapping[str, np.ndarray] = field(default_factory=_empty)
    iv_shift: np.ndarray | None = None
    widen: Mapping[str, np.ndarray] = field(default_factory=_empty)
    volume_scale: Mapping[str, np.ndarray] = field(default_factory=_empty)
    level_drop: Mapping[str, np.ndarray] = field(default_factory=_empty)
    flow_scale: Mapping[str, np.ndarray] = field(default_factory=_empty)
    buy_prob: Mapping[str, np.ndarray] = field(default_factory=_empty)
    informed: Mapping[str, Informed] = field(default_factory=_empty)
    chase_lead: Mapping[str, int] = field(default_factory=_empty)


REGULAR_DAY = Scenario()


def _merge(a: Mapping[str, Any], b: Mapping[str, Any], join: Callable[[Any, Any], Any]) -> Mapping[str, Any]:
    merged = dict(a)
    for key, value in b.items():
        merged[key] = join(merged[key], value) if key in merged else value
    return MappingProxyType(merged)


def _either_drop(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return 1.0 - (1.0 - a) * (1.0 - b)


def _later(_: Any, b: Any) -> Any:
    return b


def combine(a: Scenario, b: Scenario) -> Scenario:
    """Scales multiply, shifts add, level drops compound, and later buy-side/informed/lead settings win."""
    iv_shift = b.iv_shift if a.iv_shift is None else a.iv_shift if b.iv_shift is None else a.iv_shift + b.iv_shift
    return Scenario(
        innovation_scale=_merge(a.innovation_scale, b.innovation_scale, np.multiply),
        fair_shift=_merge(a.fair_shift, b.fair_shift, np.add),
        plug_shift=_merge(a.plug_shift, b.plug_shift, np.add),
        iv_shift=iv_shift,
        widen=_merge(a.widen, b.widen, np.add),
        volume_scale=_merge(a.volume_scale, b.volume_scale, np.multiply),
        level_drop=_merge(a.level_drop, b.level_drop, _either_drop),
        flow_scale=_merge(a.flow_scale, b.flow_scale, np.multiply),
        buy_prob=_merge(a.buy_prob, b.buy_prob, _later),
        informed=_merge(a.informed, b.informed, _later),
        chase_lead=_merge(a.chase_lead, b.chase_lead, _later),
    )
