"""One trading day of data, and staging it in the directory layout prosperity3bt reads."""

from dataclasses import dataclass
from pathlib import Path

# prosperity3bt addresses data as round<N>/..._round_<N>_day_<D>.csv. QuantiFi has a single round.
ROUND = 1


@dataclass(frozen=True)
class DayData:
    """Competition-format CSV text (semicolon separated, with headers) for one day."""

    day: int
    prices_csv: str
    trades_csv: str


def stage_day(day_data: DayData, root: Path) -> None:
    round_dir = root / f"round{ROUND}"
    round_dir.mkdir(parents=True, exist_ok=True)
    suffix = f"round_{ROUND}_day_{day_data.day}.csv"
    (round_dir / f"prices_{suffix}").write_text(day_data.prices_csv, encoding="utf-8")
    (round_dir / f"trades_{suffix}").write_text(day_data.trades_csv, encoding="utf-8")
