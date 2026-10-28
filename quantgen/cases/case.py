"""Named market cases: one YAML file each in quantgen/cases/catalog, turned into a day by `case_day`."""

import zlib
from collections.abc import Sequence
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

import numpy as np
import yaml

from quantgen.cases.context import CaseContext
from quantgen.cases.market_modifiers import ChaseLead, InformedFlow, LiquidityWindow
from quantgen.cases.param_modifiers import (
    AdjustSurface,
    ChangeCorrelation,
    OpeningGap,
    ScaleBook,
    ScaleFlow,
    ScaleJumps,
    ScaleMeanReversion,
    ScalePlug,
    ScaleVolatility,
    SetDrift,
    SetNoiseFlow,
    SetSteps,
)
from quantgen.cases.path_modifiers import DriftChange, IvShock, PlugTotalShift, Shock, TrendReversal
from quantgen.cases.vol_modifiers import FatTails, Garch, IntradayProfile, VolRegimes, VolWindow
from quantgen.generator.market import generate_day
from quantgen.generator.params import MarketParams
from quantgen.generator.scenario import REGULAR_DAY, combine
from quantgen.market_day import MarketDay
from quantgen.serde import SchemaError, from_dict

TIERS = ("observed", "plausible", "stress")
CATALOG = "catalog"

Modifier = (
    ScaleVolatility
    | ScaleFlow
    | SetNoiseFlow
    | ScaleBook
    | SetDrift
    | ScaleJumps
    | SetSteps
    | ScaleMeanReversion
    | ScalePlug
    | AdjustSurface
    | ChangeCorrelation
    | OpeningGap
    | Shock
    | TrendReversal
    | DriftChange
    | PlugTotalShift
    | IvShock
    | Garch
    | FatTails
    | VolRegimes
    | IntradayProfile
    | VolWindow
    | LiquidityWindow
    | InformedFlow
    | ChaseLead
)


@dataclass(frozen=True)
class Case:
    """A documented market situation. `event_window` bounds the shared event time, as fractions of the day."""

    id: str
    title: str
    tier: str
    family: str
    summary: str
    description: str
    references: tuple[str, ...] = ()
    modifiers: tuple[Modifier, ...] = ()
    event_window: tuple[float, float] = (0.2, 0.8)

    def __post_init__(self) -> None:
        if self.tier not in TIERS:
            raise ValueError(f"{self.id}: tier must be one of {', '.join(TIERS)}, got {self.tier!r}")
        low, high = self.event_window
        if not 0.0 <= low <= high <= 1.0:
            raise ValueError(f"{self.id}: event_window must satisfy 0 <= low <= high <= 1")


def event_tick(case: Case, seed: int, ticks: int) -> int:
    rng = np.random.default_rng([seed, zlib.crc32(f"{case.id}:event".encode())])
    low, high = case.event_window
    return int(rng.uniform(low, high) * (ticks - 1))


def case_params(params: MarketParams, case: Case, seed: int) -> tuple[MarketParams, list[CaseContext]]:
    tick = event_tick(case, seed, params.ticks)
    contexts = [CaseContext(case.id, seed, index, params.ticks, tick) for index in range(len(case.modifiers))]
    for modifier, ctx in zip(case.modifiers, contexts, strict=True):
        params = modifier.apply_params(params, ctx)
    return params, contexts


def case_day(params: MarketParams, case: Case, seed: int) -> MarketDay:
    """The case's day for `seed`. The same seed drives the same underlying randomness in every case, so differences
    between cases come from the cases themselves (common random numbers)."""
    day_params, contexts = case_params(params, case, seed)
    scenario = REGULAR_DAY
    for modifier, ctx in zip(case.modifiers, contexts, strict=True):
        scenario = combine(scenario, modifier.realize(day_params, ctx))
    return generate_day(day_params, seed, scenario)


def parse_case(text: str, source: str) -> Case:
    try:
        data = yaml.safe_load(text)
        return from_dict(Case, data)
    except (yaml.YAMLError, SchemaError, ValueError, TypeError) as error:
        raise SchemaError(f"{source}: {error}") from error


def load_catalog(directory: Path | None = None) -> list[Case]:
    """Every case in the catalog, ordered by tier then id. Each file's name must be its case id."""
    folder = directory if directory is not None else resources.files("quantgen.cases") / CATALOG
    cases = []
    for entry in sorted(folder.iterdir(), key=lambda e: e.name):
        if not entry.name.endswith(".yaml"):
            continue
        case = parse_case(entry.read_text(encoding="utf-8"), entry.name)
        if entry.name != f"{case.id}.yaml":
            raise SchemaError(f"{entry.name}: file name must be {case.id}.yaml")
        cases.append(case)
    return sorted(cases, key=lambda c: (TIERS.index(c.tier), c.id))


def find_cases(cases: Sequence[Case], ids: Sequence[str]) -> list[Case]:
    by_id = {case.id: case for case in cases}
    missing = [case_id for case_id in ids if case_id not in by_id]
    if missing:
        raise KeyError(f"unknown case(s): {', '.join(missing)}")
    return [by_id[case_id] for case_id in ids]
