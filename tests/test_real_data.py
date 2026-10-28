import hashlib
from pathlib import Path

import pytest
from prosperity3bt.file_reader import FileSystemReader
from prosperity3bt.models import TradeMatchingMode
from prosperity3bt.runner import run_backtest

from quantgen.adapter.dataset import stage_day
from quantgen.adapter.limits import quantifi_limits
from quantgen.adapter.runner import run_day
from quantgen.adapter.strategy import Strategy, load_trader
from quantgen.real_data import REAL_DAYS, load_real_day

SAMPLE_TRADER = (Path(__file__).parent / "fixtures" / "sample_trader.py").read_text()


def test_real_days_are_the_three_training_days():
    assert REAL_DAYS == (-2, -1, 0)


def test_loads_real_day_csvs_unchanged(real_data_root):
    day = load_real_day(real_data_root, 0)
    assert day.day == 0
    assert day.prices_csv.startswith("day;timestamp;product;")
    assert day.trades_csv.startswith("timestamp;buyer;seller;")


def test_missing_real_day_raises_a_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="prices_day_0.csv"):
        load_real_day(tmp_path, 0)


@pytest.mark.slow
def test_adapter_matches_running_prosperity3bt_directly(real_data_root, tmp_path):
    """Phase 1 exit criterion: our adapter produces exactly what prosperity3bt itself produces."""
    day = load_real_day(real_data_root, 0)
    ours = run_day(Strategy("sample_trader.py", SAMPLE_TRADER), day)

    stage_day(day, tmp_path)
    with quantifi_limits():
        direct = run_backtest(
            load_trader(Strategy("sample_trader.py", SAMPLE_TRADER)),
            FileSystemReader(tmp_path),
            1,
            0,
            False,
            TradeMatchingMode.all,
            True,
            False,
        )

    direct_digest = hashlib.sha256("\n".join(map(str, direct.activity_logs)).encode()).hexdigest()
    assert ours.activity_digest == direct_digest
