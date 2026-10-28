"""One trading day as arrays (for generation and statistics), and conversion to and from competition CSV text."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

import numpy as np

from quantgen.adapter.dataset import DayData

LEVELS = 3
TIMESTAMP_STEP = 100
PRICES_HEADER = (
    "day;timestamp;product;bid_price_1;bid_volume_1;bid_price_2;bid_volume_2;bid_price_3;bid_volume_3;"
    "ask_price_1;ask_volume_1;ask_price_2;ask_volume_2;ask_price_3;ask_volume_3;mid_price;profit_and_loss"
)
TRADES_HEADER = "timestamp;buyer;seller;symbol;currency;price;quantity"
CURRENCY = "COINS"


@dataclass(frozen=True)
class ProductDay:
    """Order book snapshots (one row per tick, NaN where a level is absent) and the market trade tape."""

    bid_prices: np.ndarray
    bid_volumes: np.ndarray
    ask_prices: np.ndarray
    ask_volumes: np.ndarray
    trade_ticks: np.ndarray
    trade_prices: np.ndarray
    trade_quantities: np.ndarray

    @property
    def ticks(self) -> int:
        return self.bid_prices.shape[0]

    @property
    def mid(self) -> np.ndarray:
        return (self.bid_prices[:, 0] + self.ask_prices[:, 0]) / 2


@dataclass(frozen=True)
class MarketDay:
    day: int
    products: Mapping[str, ProductDay]

    @property
    def ticks(self) -> int:
        return next(iter(self.products.values())).ticks


def _cells(values: np.ndarray) -> list[str]:
    """Integer cells, empty where the level is absent."""
    present = ~np.isnan(values)
    text = np.where(present, np.nan_to_num(values).astype(np.int64).astype(str), "")
    return text.tolist()


def _price_lines(day: int, product: str, book: ProductDay) -> list[str]:
    columns = []
    for prices, volumes in ((book.bid_prices, book.bid_volumes), (book.ask_prices, book.ask_volumes)):
        for level in range(LEVELS):
            columns.append(_cells(prices[:, level]))
            columns.append(_cells(volumes[:, level]))
    mids = [f"{mid:.1f}" for mid in book.mid.tolist()]
    return [
        f"{day};{tick * TIMESTAMP_STEP};{product};{';'.join(cells)};{mid};0.0"
        for tick, (cells, mid) in enumerate(zip(zip(*columns, strict=True), mids, strict=True))
    ]


def to_day_data(market: MarketDay) -> DayData:
    """Competition-format CSVs: prices sorted by timestamp then product, trades by timestamp then symbol."""
    names = sorted(market.products)
    per_product = [_price_lines(market.day, name, market.products[name]) for name in names]
    price_lines = [PRICES_HEADER, *(line for tick_lines in zip(*per_product, strict=True) for line in tick_lines)]

    trades = []
    for name in names:
        book = market.products[name]
        for tick, price, quantity in zip(
            book.trade_ticks.tolist(), book.trade_prices.tolist(), book.trade_quantities.tolist(), strict=True
        ):
            trades.append((tick, name, price, quantity))
    trades.sort(key=lambda trade: (trade[0], trade[1]))
    trade_lines = [TRADES_HEADER] + [
        f"{tick * TIMESTAMP_STEP};;;{name};{CURRENCY};{float(price)};{int(quantity)}"
        for tick, name, price, quantity in trades
    ]
    return DayData(day=market.day, prices_csv="\n".join(price_lines) + "\n", trades_csv="\n".join(trade_lines) + "\n")


def _float(cell: str) -> float:
    return float(cell) if cell else np.nan


def _parse_prices(text: str) -> dict[str, list[list[float]]]:
    rows: dict[str, list[list[float]]] = {}
    for line in text.splitlines()[1:]:
        cells = line.split(";")
        if len(cells) < 15:
            continue
        rows.setdefault(cells[2], []).append([_float(cell) for cell in cells[3:15]])
    return rows


def _parse_trades(text: str) -> dict[str, list[tuple[int, float, int]]]:
    trades: dict[str, list[tuple[int, float, int]]] = {}
    for line in text.splitlines()[1:]:
        cells = line.split(";")
        if len(cells) < 7:
            continue
        tick = int(cells[0]) // TIMESTAMP_STEP
        trades.setdefault(cells[3], []).append((tick, float(cells[5]), int(cells[6])))
    return trades


def _product_day(rows: list[list[float]], trades: list[tuple[int, float, int]]) -> ProductDay:
    book = np.asarray(rows, dtype=float)
    tape = np.asarray(trades, dtype=float).reshape(-1, 3)
    return ProductDay(
        bid_prices=book[:, 0:6:2],
        bid_volumes=book[:, 1:6:2],
        ask_prices=book[:, 6:12:2],
        ask_volumes=book[:, 7:12:2],
        trade_ticks=tape[:, 0].astype(np.int64),
        trade_prices=tape[:, 1],
        trade_quantities=tape[:, 2].astype(np.int64),
    )


def from_day_data(day_data: DayData) -> MarketDay:
    """Parse competition CSVs. Assumes one row per product per timestamp, in timestamp order (as in the real files)."""
    rows = _parse_prices(day_data.prices_csv)
    trades = _parse_trades(day_data.trades_csv)
    products = {name: _product_day(book_rows, trades.get(name, [])) for name, book_rows in sorted(rows.items())}
    return MarketDay(day=day_data.day, products=MappingProxyType(products))
