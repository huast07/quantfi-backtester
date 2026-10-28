from pathlib import Path

import pytest
from conftest import PRICES_HEADER, TRADES_HEADER, price_row, trade_row

from quantgen.cases.case import load_catalog
from quantgen.cli import main
from quantgen.generator.params import save_params
from quantgen.real_data import PRICES_DIR, TRADES_DIR

BUY_ONCE = """
from datamodel import Order

class Trader:
    def run(self, state):
        if state.timestamp == 0:
            return {"AMETHYST": [Order("AMETHYST", 10002, 2)]}, 0, ""
        return {}, 0, ""
"""

IDLE = """
class Trader:
    def run(self, state):
        return {}, 0, ""
"""


def write_real_layout(root: Path, day: int) -> None:
    (root / PRICES_DIR).mkdir(parents=True, exist_ok=True)
    (root / TRADES_DIR).mkdir(parents=True, exist_ok=True)
    prices = [PRICES_HEADER] + [price_row(ts, "AMETHYST", 9998, 10002, day=day) for ts in (0, 100, 200)]
    (root / PRICES_DIR / f"prices_day_{day}.csv").write_text("\n".join(prices) + "\n")
    (root / TRADES_DIR / f"trades_day_{day}.csv").write_text(TRADES_HEADER + "\n" + trade_row(100, "AMETHYST", 9999, 1))


def test_run_real_prints_one_row_per_strategy_with_per_day_and_total_pnl(tmp_path, capsys):
    write_real_layout(tmp_path, 0)
    buy = tmp_path / "buy.py"
    idle = tmp_path / "idle.py"
    buy.write_text(BUY_ONCE)
    idle.write_text(IDLE)

    code = main(["run", str(buy), str(idle), "--real", "--days", "0", "--data-root", str(tmp_path)])

    out = capsys.readouterr().out
    assert code == 0
    assert "buy.py" in out and "idle.py" in out
    assert "-4" in out


def test_invalid_strategy_reports_the_problem_and_exits_nonzero(tmp_path, capsys):
    write_real_layout(tmp_path, 0)
    bad = tmp_path / "bad.py"
    bad.write_text("x = 1\n")

    code = main(["run", str(bad), "--real", "--days", "0", "--data-root", str(tmp_path)])

    assert code == 1
    assert "does not define a Trader class" in capsys.readouterr().err


def test_missing_strategy_file_exits_nonzero(tmp_path, capsys):
    code = main(["run", str(tmp_path / "nope.py"), "--real", "--data-root", str(tmp_path)])
    assert code == 1
    assert "nope.py" in capsys.readouterr().err


def test_gen_writes_a_prosperity3bt_layout_that_is_the_same_for_the_same_seed(tmp_path, calibrated_params):
    params = tmp_path / "params.json"
    save_params(calibrated_params, params)

    first = main(["gen", "--seed", "3", "--params", str(params), "--out", str(tmp_path / "a")])
    second = main(["gen", "--seed", "3", "--params", str(params), "--out", str(tmp_path / "b")])

    csv = "round1/prices_round_1_day_1.csv"
    assert first == second == 0
    assert (tmp_path / "a" / csv).read_bytes() == (tmp_path / "b" / csv).read_bytes()
    assert (tmp_path / "a" / "round1" / "trades_round_1_day_1.csv").is_file()


def test_gen_with_a_missing_params_file_exits_nonzero(tmp_path, capsys):
    code = main(["gen", "--seed", "1", "--params", str(tmp_path / "none.json"), "--out", str(tmp_path)])

    assert code == 1
    assert "none.json" in capsys.readouterr().err


def test_gen_with_a_stale_params_file_reports_the_schema_problem(tmp_path, capsys):
    params = tmp_path / "params.json"
    params.write_text('{"format_version": 0}')

    code = main(["gen", "--seed", "1", "--params", str(params), "--out", str(tmp_path)])

    assert code == 1
    assert "error:" in capsys.readouterr().err


@pytest.mark.slow
def test_calibrate_then_fidelity_passes_on_the_real_days(tmp_path, real_data_root, capsys):
    params = tmp_path / "params.json"

    calibrated = main(["calibrate", "--data-root", str(real_data_root), "--out", str(params)])
    checked = main(["fidelity", "--params", str(params), "--data-root", str(real_data_root), "--seeds", "1", "2", "3"])

    assert calibrated == checked == 0
    assert "checks passed" in capsys.readouterr().out


def test_cases_lists_the_whole_catalog(capsys):
    assert main(["cases"]) == 0

    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == len(load_catalog())
    assert any(line.startswith("black-swan-crash") and "stress" in line for line in lines)


def test_gen_with_an_unknown_case_exits_nonzero(tmp_path, capsys, calibrated_params):
    params = tmp_path / "params.json"
    save_params(calibrated_params, params)

    code = main(["gen", "--seed", "1", "--case", "no-such-case", "--params", str(params), "--out", str(tmp_path)])

    assert code == 1
    assert "no-such-case" in capsys.readouterr().err


def test_run_rejects_a_strategy_named_like_the_reference(tmp_path, capsys):
    strategy = tmp_path / "reference"
    strategy.write_text(IDLE)

    code = main(["run", str(strategy), "--cases", "regular-day", "--seeds", "1", "--workers", "1"])

    assert code == 1
    assert "unique" in capsys.readouterr().err


@pytest.mark.slow
def test_run_on_cases_prints_profiles_and_a_matrix(tmp_path, capsys, calibrated_params):
    params = tmp_path / "params.json"
    save_params(calibrated_params, params)
    buy = tmp_path / "buy.py"
    buy.write_text(BUY_ONCE)

    code = main(["run", str(buy), "--cases", "regular-day", "--seeds", "1", "--workers", "1", "--params", str(params)])

    out = capsys.readouterr().out
    assert code == 0
    assert "== buy.py ==" in out and "Performs well in:" in out and "Performs poorly in:" in out
    assert "reference" in out and "regular-day" in out
