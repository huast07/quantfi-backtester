import pytest

from quantgen.adapter.strategy import Strategy, StrategyError, load_trader

VALID = """
from datamodel import Order, TradingState

class Trader:
    def run(self, state: TradingState):
        return {}, 0, ""
"""

STATEFUL = """
CALLS = []

class Trader:
    def run(self, state):
        CALLS.append(1)
        return {}, 0, str(len(CALLS))
"""


def test_loads_a_trader_that_imports_the_competition_datamodel():
    trader = load_trader(Strategy("valid.py", VALID))
    assert callable(trader.run)


def test_each_load_gets_a_fresh_module_so_runs_cannot_leak_state():
    first = load_trader(Strategy("s.py", STATEFUL))
    second = load_trader(Strategy("s.py", STATEFUL))
    assert first.run(None)[2] == "1"
    assert second.run(None)[2] == "1"


def test_syntax_error_reports_file_and_line():
    with pytest.raises(StrategyError, match=r"bad\.py: syntax error on line 2"):
        load_trader(Strategy("bad.py", "x = 1\ndef broken(:\n"))


def test_missing_trader_class_is_rejected():
    with pytest.raises(StrategyError, match="does not define a Trader class"):
        load_trader(Strategy("empty.py", "x = 1\n"))


def test_trader_without_run_method_is_rejected():
    with pytest.raises(StrategyError, match=r"run\(\) method"):
        load_trader(Strategy("norun.py", "class Trader:\n    pass\n"))


def test_unavailable_import_names_the_missing_module():
    with pytest.raises(StrategyError, match="imports 'sklearn', which is not available"):
        load_trader(Strategy("ml.py", "import sklearn\nclass Trader:\n    def run(self, s):\n        pass\n"))


def test_error_raised_at_import_time_is_reported():
    with pytest.raises(StrategyError, match="failed while loading"):
        load_trader(Strategy("crash.py", "raise ValueError('nope')\n"))
