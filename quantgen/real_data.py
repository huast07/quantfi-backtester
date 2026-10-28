"""Load the three QuantiFi training days exactly as provided."""

from pathlib import Path

from quantgen.adapter.dataset import DayData

REAL_DAYS: tuple[int, ...] = (-2, -1, 0)
PRICES_DIR = "QuantFi Price Data"
TRADES_DIR = "QuantFi Trades Data"


def load_real_day(data_root: Path, day: int) -> DayData:
    prices = data_root / PRICES_DIR / f"prices_day_{day}.csv"
    trades = data_root / TRADES_DIR / f"trades_day_{day}.csv"
    for path in (prices, trades):
        if not path.is_file():
            raise FileNotFoundError(f"QuantiFi data file not found: {path}")
    return DayData(
        day=day,
        prices_csv=prices.read_text(encoding="utf-8"),
        trades_csv=trades.read_text(encoding="utf-8"),
    )
