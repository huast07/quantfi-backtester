from pathlib import Path

import pytest

from quantgen.adapter.dataset import DayData

PRICES_HEADER = (
    "day;timestamp;product;bid_price_1;bid_volume_1;bid_price_2;bid_volume_2;bid_price_3;bid_volume_3;"
    "ask_price_1;ask_volume_1;ask_price_2;ask_volume_2;ask_price_3;ask_volume_3;mid_price;profit_and_loss"
)
TRADES_HEADER = "timestamp;buyer;seller;symbol;currency;price;quantity"

REPO_ROOT = Path(__file__).resolve().parent.parent


def price_row(timestamp: int, product: str, bid: int, ask: int, volume: int = 10, day: int = 1) -> str:
    mid = (bid + ask) / 2
    return f"{day};{timestamp};{product};{bid};{volume};;;;;{ask};{volume};;;;;{mid};0.0"


def trade_row(timestamp: int, symbol: str, price: int, quantity: int) -> str:
    return f"{timestamp};;;{symbol};COINS;{float(price)};{quantity}"


@pytest.fixture
def tiny_day() -> DayData:
    """Three ticks of AMETHYST quoted 9998/10002, with one market trade at 9999 on the second tick."""
    prices = [PRICES_HEADER] + [price_row(ts, "AMETHYST", 9998, 10002) for ts in (0, 100, 200)]
    trades = [TRADES_HEADER, trade_row(100, "AMETHYST", 9999, 3)]
    return DayData(day=1, prices_csv="\n".join(prices) + "\n", trades_csv="\n".join(trades) + "\n")


@pytest.fixture
def real_data_root() -> Path:
    root = REPO_ROOT
    if not (root / "QuantFi Price Data" / "prices_day_0.csv").is_file():
        pytest.skip("real QuantFi CSVs are not present")
    return root


@pytest.fixture(scope="session")
def calibrated_params():
    from quantgen.generator.params import load_params

    path = REPO_ROOT / "params" / "params.json"
    if not path.is_file():
        pytest.skip("params/params.json has not been generated (run `quantgen calibrate`)")
    return load_params(path)
