import prosperity3bt.data as p3data
import pytest

from quantgen.adapter.runner import MatchMode, run_day
from quantgen.adapter.strategy import Strategy

TAKE_ASK_ONCE = """
from datamodel import Order

class Trader:
    def run(self, state):
        if state.timestamp == 0:
            return {"AMETHYST": [Order("AMETHYST", 10002, 2)]}, 0, ""
        return {}, 0, ""
"""

BID_AT_9999 = """
from datamodel import Order

class Trader:
    def run(self, state):
        if state.timestamp == 100:
            return {"AMETHYST": [Order("AMETHYST", 9999, 5)]}, 0, ""
        return {}, 0, ""
"""

OVER_LIMIT = """
from datamodel import Order

class Trader:
    def run(self, state):
        return {"AMETHYST": [Order("AMETHYST", 10002, 51)]}, 0, ""
"""

PRINTS = """
class Trader:
    def run(self, state):
        print("hello from", state.timestamp)
        return {}, 0, ""
"""


def test_aggressive_buy_fills_at_the_ask_and_is_marked_to_mid(tiny_day):
    result = run_day(Strategy("take.py", TAKE_ASK_ONCE), tiny_day)

    assert result.own_trade_count == 1
    # Bought 2 at 10,002, marked at mid 10,000: -4 once the position shows in the next tick's log row.
    assert result.product_pnl["AMETHYST"] == pytest.approx(-4.0)
    assert result.total_pnl == pytest.approx(-4.0)


def test_passive_bid_fills_on_equal_price_trade_under_the_wiki_rule(tiny_day):
    result = run_day(Strategy("bid.py", BID_AT_9999), tiny_day, MatchMode.ALL)
    assert result.own_trade_count == 1
    assert result.final_positions["AMETHYST"] == 3


def test_passive_bid_does_not_fill_on_equal_price_trade_in_worse_mode(tiny_day):
    result = run_day(Strategy("bid.py", BID_AT_9999), tiny_day, MatchMode.WORSE)
    assert result.own_trade_count == 0
    assert result.final_positions.get("AMETHYST", 0) == 0


def test_orders_that_could_breach_the_limit_are_cancelled_and_counted(tiny_day):
    result = run_day(Strategy("over.py", OVER_LIMIT), tiny_day)
    assert result.own_trade_count == 0
    assert result.limit_breaches == 3


def test_pnl_path_has_one_point_per_tick(tiny_day):
    result = run_day(Strategy("take.py", TAKE_ASK_ONCE), tiny_day)
    assert result.pnl_path == pytest.approx((0.0, -4.0, -4.0))


def test_trader_stdout_is_captured_in_the_visualizer_log(tiny_day):
    result = run_day(Strategy("print.py", PRINTS), tiny_day)
    assert "hello from 100" in result.log
    assert result.log.startswith("Sandbox logs:")


def test_prosperity3bt_limits_are_left_untouched_after_a_run(tiny_day):
    before = dict(p3data.LIMITS)
    run_day(Strategy("take.py", TAKE_ASK_ONCE), tiny_day)
    assert p3data.LIMITS == before


def test_runs_without_a_log_skip_the_log_and_digest_but_keep_the_pnl(tiny_day):
    full = run_day(Strategy("take.py", TAKE_ASK_ONCE), tiny_day)
    lean = run_day(Strategy("take.py", TAKE_ASK_ONCE), tiny_day, with_log=False)

    assert lean.log is None and lean.activity_digest is None
    assert lean.total_pnl == full.total_pnl and lean.pnl_path == full.pnl_path
