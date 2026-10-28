"""Calibrated generator parameters (params/params.json): one entry per product plus cross-product structure."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from quantgen.generator.book import BookParams
from quantgen.generator.processes import Process, VoucherSurface
from quantgen.generator.takers import Flow
from quantgen.serde import SchemaError, from_dict, to_dict

FORMAT_VERSION = 1


@dataclass(frozen=True)
class ProductParams:
    start: float
    process: Process
    quote_noise_sd: float
    book: BookParams
    flow: Flow


@dataclass(frozen=True)
class Correlation:
    """Correlation of fair-value innovations across `products` (row/column order of `matrix`)."""

    products: tuple[str, ...]
    matrix: tuple[tuple[float, ...], ...]


@dataclass(frozen=True)
class MarketParams:
    format_version: int
    day: int
    ticks: int
    products: Mapping[str, ProductParams]
    correlation: Correlation
    voucher_surface: VoucherSurface


def load_params(path: Path) -> MarketParams:
    params = from_dict(MarketParams, json.loads(path.read_text(encoding="utf-8")))
    if params.format_version != FORMAT_VERSION:
        raise SchemaError(f"{path}: format_version {params.format_version}, expected {FORMAT_VERSION}")
    return params


def save_params(params: MarketParams, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_dict(params), indent=1) + "\n", encoding="utf-8")
