"""Per-tick traces of one run, for the web app's drill-down charts (prices with fills, position, PnL, trader logs)."""

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from prosperity3bt.models import BacktestResult

from quantgen.adapter.runner import SUBMISSION

PRODUCT_COLUMN, MID_COLUMN, PNL_COLUMN = 2, -2, -1
MAX_LOG_CHARS = 200_000


@dataclass(frozen=True)
class Fill:
    timestamp: int
    price: float
    quantity: int  # positive when we bought


@dataclass(frozen=True)
class ProductTrace:
    product: str
    mid: tuple[float, ...]
    pnl: tuple[float, ...]
    position: tuple[int, ...]
    fills: tuple[Fill, ...]


@dataclass(frozen=True)
class LogLine:
    timestamp: int
    text: str


@dataclass(frozen=True)
class RunDetail:
    """`products` holds a trace for every product the strategy traded or made PnL on; `product_pnl` covers all."""

    timestamps: tuple[int, ...]
    total_pnl: tuple[float, ...]
    product_pnl: Mapping[str, float]
    products: tuple[ProductTrace, ...]
    logs: tuple[LogLine, ...]
    logs_truncated: bool


def _fills(result: BacktestResult) -> dict[str, list[Fill]]:
    fills: dict[str, list[Fill]] = defaultdict(list)
    for row in result.trades:
        trade = row.trade
        if SUBMISSION not in (trade.buyer, trade.seller):
            continue
        signed = trade.quantity if trade.buyer == SUBMISSION else -trade.quantity
        fills[trade.symbol].append(Fill(trade.timestamp, float(trade.price), signed))
    return fills


def _positions(timestamps: tuple[int, ...], fills: list[Fill]) -> tuple[int, ...]:
    """Position after each tick's fills."""
    by_tick: dict[int, int] = defaultdict(int)
    for fill in fills:
        by_tick[fill.timestamp] += fill.quantity
    position, out = 0, []
    for timestamp in timestamps:
        position += by_tick.get(timestamp, 0)
        out.append(position)
    return tuple(out)


def _logs(result: BacktestResult) -> tuple[tuple[LogLine, ...], bool]:
    """Trader prints and limit warnings per tick, capped so the drill-down stays responsive."""
    lines, used = [], 0
    for row in result.sandbox_logs:
        text = "\n".join(part for part in (row.lambda_log, row.sandbox_log.strip()) if part)
        if not text:
            continue
        if used + len(text) > MAX_LOG_CHARS:
            return tuple(lines), True
        lines.append(LogLine(row.timestamp, text))
        used += len(text)
    return tuple(lines), False


def run_detail(result: BacktestResult) -> RunDetail:
    mids: dict[str, list[float]] = defaultdict(list)
    pnls: dict[str, list[float]] = defaultdict(list)
    for row in result.activity_logs:
        product = row.columns[PRODUCT_COLUMN]
        mids[product].append(float(row.columns[MID_COLUMN]))
        pnls[product].append(float(row.columns[PNL_COLUMN]))
    timestamps = tuple(sorted({row.timestamp for row in result.activity_logs}))
    fills = _fills(result)
    final = {product: path[-1] for product, path in pnls.items()}
    active = sorted(product for product in pnls if fills.get(product) or final[product] != 0)
    traces = tuple(
        ProductTrace(
            product=product,
            mid=tuple(mids[product]),
            pnl=tuple(pnls[product]),
            position=_positions(timestamps, fills.get(product, [])),
            fills=tuple(fills.get(product, [])),
        )
        for product in active
    )
    total = tuple(sum(path[i] for path in pnls.values()) for i in range(len(timestamps)))
    logs, truncated = _logs(result)
    return RunDetail(timestamps, total, MappingProxyType(final), traces, logs, truncated)
