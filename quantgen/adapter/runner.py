"""Run one strategy on one day through prosperity3bt and summarise the result."""

import tempfile
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from prosperity3bt.file_reader import FileSystemReader
from prosperity3bt.models import BacktestResult, TradeMatchingMode
from prosperity3bt.runner import run_backtest

from quantgen.adapter.dataset import ROUND, DayData, stage_day
from quantgen.adapter.limits import quantifi_limits
from quantgen.adapter.result_log import activity_digest, format_log
from quantgen.adapter.strategy import Strategy, load_trader


class MatchMode:
    """prosperity3bt's passive-fill rules. ALL is the QuantiFi wiki rule ("equal or better" fills)."""

    ALL = TradeMatchingMode.all
    WORSE = TradeMatchingMode.worse
    NONE = TradeMatchingMode.none


SUBMISSION = "SUBMISSION"
LIMIT_BREACH_MARKER = "exceeded limit"


@dataclass(frozen=True)
class DayResult:
    """`activity_digest` and `log` are None when the run was made with `with_log=False` (suite runs, where building
    the ~19 MB log would take about a quarter of the run time and is thrown away)."""

    day: int
    product_pnl: Mapping[str, float]
    total_pnl: float
    pnl_path: tuple[float, ...]
    final_positions: Mapping[str, int]
    own_trade_count: int
    limit_breaches: int
    activity_digest: str | None
    log: str | None


def backtest(strategy: Strategy, day_data: DayData, match_mode: TradeMatchingMode = MatchMode.ALL) -> BacktestResult:
    """prosperity3bt's raw result for one strategy on one day."""
    trader = load_trader(strategy)
    with tempfile.TemporaryDirectory(prefix="quantgen-") as tmp, quantifi_limits():
        root = Path(tmp)
        stage_day(day_data, root)
        return run_backtest(trader, FileSystemReader(root), ROUND, day_data.day, False, match_mode, True, False)


def run_day(
    strategy: Strategy, day_data: DayData, match_mode: TradeMatchingMode = MatchMode.ALL, with_log: bool = True
) -> DayResult:
    return summarise(day_data.day, backtest(strategy, day_data, match_mode), with_log)


def summarise(day: int, result: BacktestResult, with_log: bool = True) -> DayResult:
    pnl_by_timestamp: dict[int, float] = defaultdict(float)
    for row in result.activity_logs:
        pnl_by_timestamp[row.timestamp] += row.columns[-1]

    last_timestamp = result.activity_logs[-1].timestamp
    product_pnl = {row.columns[2]: row.columns[-1] for row in result.activity_logs if row.timestamp == last_timestamp}

    own_trades = [row.trade for row in result.trades if SUBMISSION in (row.trade.buyer, row.trade.seller)]
    positions: dict[str, int] = defaultdict(int)
    for trade in own_trades:
        positions[trade.symbol] += trade.quantity if trade.buyer == SUBMISSION else -trade.quantity

    return DayResult(
        day=day,
        product_pnl=MappingProxyType(product_pnl),
        total_pnl=sum(product_pnl.values()),
        pnl_path=tuple(pnl_by_timestamp[ts] for ts in sorted(pnl_by_timestamp)),
        final_positions=MappingProxyType({symbol: qty for symbol, qty in positions.items() if qty != 0}),
        own_trade_count=len(own_trades),
        limit_breaches=sum(row.sandbox_log.count(LIMIT_BREACH_MARKER) for row in result.sandbox_logs),
        activity_digest=activity_digest(result) if with_log else None,
        log=format_log(result) if with_log else None,
    )
