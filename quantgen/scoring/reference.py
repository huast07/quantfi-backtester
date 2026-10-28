"""Load the built-in reference strategy (reference_trader.py) as an uploadable Strategy."""

from importlib import resources

from quantgen.adapter.strategy import Strategy

REFERENCE_NAME = "reference"


def reference_strategy() -> Strategy:
    source = (resources.files("quantgen.scoring") / "reference_trader.py").read_text(encoding="utf-8")
    return Strategy(name=REFERENCE_NAME, source=source)
