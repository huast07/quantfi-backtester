from types import MappingProxyType

import numpy as np
import pytest

from quantgen.calibration.calibrate import load_real_market_days, real_expiries
from quantgen.calibration.fidelity import Check, format_report, run_fidelity
from quantgen.calibration.stats import Tolerance, batch_sd, buy_share, taker_markout, voucher_taker_markout
from quantgen.market_day import MarketDay, ProductDay

FIDELITY_SEEDS = (1, 2, 3, 4, 5)


def test_a_check_passes_inside_the_widened_real_range():
    assert Check("X", "s", 1.0, 2.0, 2.4, 0.5).passed
    assert not Check("X", "s", 1.0, 2.0, 2.6, 0.5).passed


def test_report_lists_only_failures_when_asked():
    checks = [Check("A", "ok stat", 0.0, 1.0, 0.5, 0.0), Check("B", "bad stat", 0.0, 1.0, 3.0, 0.1)]

    report = format_report(checks, failures_only=True)

    assert "bad stat" in report and "ok stat" not in report
    assert "1/2 checks passed" in report


@pytest.mark.slow
def test_generated_days_reproduce_the_real_stylized_facts(calibrated_params, real_data_root):
    checks = run_fidelity(calibrated_params, load_real_market_days(real_data_root), real_expiries(), FIDELITY_SEEDS)

    assert all(check.passed for check in checks), format_report(checks, failures_only=True)


def test_sampling_term_widens_the_margin_by_the_day_level_standard_error():
    tolerance = Tolerance(absolute=0.08, sampling_z=2.0)

    assert tolerance.margin([0.5, 0.55], [0.5, 0.5, 0.5], day_sd=0.01) == pytest.approx(0.08)
    expected = 2.0 * 0.1 * np.sqrt(1 / 2 + 1 / 3)
    assert tolerance.margin([0.5, 0.55], [0.5, 0.5, 0.5], day_sd=0.1) == pytest.approx(expected)


def test_batch_means_recover_the_sd_of_a_whole_day_statistic():
    rng = np.random.default_rng(7)
    days = [_noise_day(rng) for _ in range(20)]

    estimate = batch_sd(buy_share, days)

    actual = np.std([buy_share(day) for day in [_noise_day(rng) for _ in range(300)]])
    assert estimate == pytest.approx(actual, rel=0.25)


def _noise_day(rng: np.random.Generator, ticks: int = 10_000) -> ProductDay:
    bids = np.full((ticks, 3), np.nan)
    asks = np.full((ticks, 3), np.nan)
    bids[:, 0], asks[:, 0] = 99.0, 101.0
    volumes = np.where(np.isnan(bids), 0, 5).astype(np.int64)
    trade_ticks = np.sort(rng.choice(ticks, size=400, replace=False))
    prices = np.where(rng.random(400) < 0.5, 101.0, 99.0)
    return ProductDay(bids, volumes, asks, volumes, trade_ticks, prices, np.ones(400, dtype=np.int64))


def test_without_a_sampling_term_the_margin_ignores_the_generated_spread():
    assert Tolerance(relative=0.1).margin([90.0, 110.0], [0.0, 500.0], day_sd=50.0) == pytest.approx(10.0)


def _day_with_takers(mid_after: float) -> ProductDay:
    ticks = 20
    bids = np.full((ticks, 3), np.nan)
    asks = np.full((ticks, 3), np.nan)
    bids[:, 0], asks[:, 0] = 99.0, 101.0
    bids[11:, 0], asks[11:, 0] = mid_after - 1, mid_after + 1
    volumes = np.where(np.isnan(bids), 0, 5).astype(np.int64)
    return ProductDay(
        bid_prices=bids,
        bid_volumes=volumes,
        ask_prices=asks,
        ask_volumes=volumes,
        trade_ticks=np.array([5, 10]),
        trade_prices=np.array([101.0, 99.0]),
        trade_quantities=np.array([1, 1]),
    )


def test_taker_markout_is_the_side_signed_mid_move_after_each_print():
    day = _day_with_takers(mid_after=104.0)

    assert taker_markout(day, horizon=1) == pytest.approx((0.0 + -4.0) / 2)
    assert taker_markout(day, horizon=10) == pytest.approx((4.0 + -4.0) / 2)


def test_voucher_markout_pools_every_voucher_print_of_the_day():
    up, flat = _day_with_takers(mid_after=104.0), _day_with_takers(mid_after=100.0)
    market = MarketDay(day=1, products=MappingProxyType({"VOUCHER_7000": up, "VOUCHER_7500": flat, "LYCHEE": up}))

    assert voucher_taker_markout(market, horizon=10) == pytest.approx((4.0 - 4.0 + 0.0 + 0.0) / 4)
    assert voucher_taker_markout(market, horizon=1) == pytest.approx((0.0 - 4.0 + 0.0 + 0.0) / 4)
