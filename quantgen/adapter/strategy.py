"""Load an uploaded trader.py into a fresh module, the way the competition backtester imports it."""

import sys
import types
from dataclasses import dataclass
from itertools import count
from typing import Any

import prosperity3bt.datamodel

_module_ids = count()


class StrategyError(Exception):
    """The uploaded file cannot be used as a strategy. The message is safe to show to the user."""


@dataclass(frozen=True)
class Strategy:
    name: str
    source: str


def _expose_datamodel() -> None:
    # Traders write `from datamodel import ...`; the competition provides that module, prosperity3bt ships it.
    sys.modules.setdefault("datamodel", prosperity3bt.datamodel)


def _execute(strategy: Strategy) -> types.ModuleType:
    try:
        code = compile(strategy.source, strategy.name, "exec")
    except SyntaxError as error:
        raise StrategyError(f"{strategy.name}: syntax error on line {error.lineno}: {error.msg}") from error

    module = types.ModuleType(f"quantgen_strategy_{next(_module_ids)}")
    module.__file__ = strategy.name
    try:
        exec(code, module.__dict__)
    except ModuleNotFoundError as error:
        raise StrategyError(f"{strategy.name} imports '{error.name}', which is not available") from error
    except Exception as error:
        raise StrategyError(f"{strategy.name} failed while loading: {error!r}") from error
    return module


def load_trader(strategy: Strategy) -> Any:
    """Return a new Trader instance from a fresh module, so no state carries over between runs."""
    _expose_datamodel()
    module = _execute(strategy)

    trader_class = getattr(module, "Trader", None)
    if not isinstance(trader_class, type):
        raise StrategyError(f"{strategy.name} does not define a Trader class")
    if not callable(getattr(trader_class, "run", None)):
        raise StrategyError(f"{strategy.name}: the Trader class has no run() method")

    try:
        return trader_class()
    except Exception as error:
        raise StrategyError(f"{strategy.name}: Trader() failed: {error!r}") from error
