from dataclasses import replace
from types import MappingProxyType

import numpy as np
import pytest

from quantgen.adapter.runner import run_day
from quantgen.adapter.strategy import Strategy
from quantgen.generator.market import generate_day
from quantgen.generator.params import load_params, save_params
from quantgen.market_day import from_day_data, to_day_data

PEARLS = ("WHITE_PEARLS", "BLACK_PEARLS", "GOLDEN_PEARLS", "PINK_PEARLS", "BLUE_PEARLS")
PEARL_TOTAL = 50_000.0
MAX_PEARL_GAP = 60.0

TAKE_AMETHYST_ASK = """
from datamodel import Order

class Trader:
    def run(self, state):
        if state.timestamp == 0:
            depth = state.order_depths["AMETHYST"]
            ask = min(depth.sell_orders)
            return {"AMETHYST": [Order("AMETHYST", ask, 1)]}, 0, ""
        return {}, 0, ""
"""

MAX_ONE_TICK_BETA_SHARE = 0.5
MIN_TELLURIUM_NEXT_TICK_IMPACT = 1.5


@pytest.fixture(scope="module")
def day_one(calibrated_params):
    return generate_day(calibrated_params, seed=1)


def test_same_seed_gives_an_identical_day(calibrated_params, day_one):
    again = generate_day(calibrated_params, seed=1)

    assert to_day_data(again) == to_day_data(day_one)


def test_different_seeds_give_different_days(calibrated_params, day_one):
    other = generate_day(calibrated_params, seed=2)

    assert not np.array_equal(other.products["LYCHEE"].mid, day_one.products["LYCHEE"].mid)


def test_every_product_has_a_full_day_of_uncrossed_books(calibrated_params, day_one):
    assert set(day_one.products) == set(calibrated_params.products)
    for name, product in day_one.products.items():
        assert product.ticks == calibrated_params.ticks, name
        assert np.all(product.bid_prices[:, 0] < product.ask_prices[:, 0]), name
        assert np.all(np.diff(product.bid_prices[:, :2], axis=1)[~np.isnan(product.bid_prices[:, 1])] < 0), name


def test_market_trades_print_inside_the_same_tick_book(day_one):
    """Takers trade at a quoted level: never inside the spread and never past the deepest level."""
    for name, product in day_one.products.items():
        ticks = product.trade_ticks
        low = np.nanmin(product.bid_prices[ticks], axis=1)
        high = np.nanmax(product.ask_prices[ticks], axis=1)
        assert np.all((product.trade_prices >= low) & (product.trade_prices <= high)), name
        inside = (product.trade_prices > product.bid_prices[ticks, 0]) & (
            product.trade_prices < product.ask_prices[ticks, 0]
        )
        assert not inside.any(), name
        assert np.all(product.trade_quantities > 0), name


def test_pearls_keep_their_total_through_golden_steps(day_one):
    total = sum(day_one.products[name].mid for name in PEARLS)

    assert np.max(np.abs(total - PEARL_TOTAL)) < MAX_PEARL_GAP


def test_csv_round_trip_preserves_books_and_tapes(day_one):
    restored = from_day_data(to_day_data(day_one))

    for name, product in day_one.products.items():
        again = restored.products[name]
        np.testing.assert_array_equal(again.bid_prices, product.bid_prices, err_msg=name)
        np.testing.assert_array_equal(again.ask_volumes, product.ask_volumes, err_msg=name)
        order = np.argsort(product.trade_ticks, kind="stable")
        np.testing.assert_array_equal(again.trade_ticks, product.trade_ticks[order], err_msg=name)
        np.testing.assert_array_equal(again.trade_quantities, product.trade_quantities[order], err_msg=name)


def test_params_survive_a_json_round_trip(calibrated_params, tmp_path):
    path = tmp_path / "params.json"

    save_params(calibrated_params, path)

    assert load_params(path) == calibrated_params


@pytest.mark.slow
def test_prosperity3bt_runs_a_strategy_on_a_generated_day(day_one):
    result = run_day(Strategy(name="take.py", source=TAKE_AMETHYST_ASK), to_day_data(day_one))

    assert result.day == 1
    assert result.total_pnl != 0


def _beta(day, product: str, horizon: int) -> float:
    spot = day.products["LYCHEE"].mid
    voucher = day.products[product].mid
    x, y = spot[horizon:] - spot[:-horizon], voucher[horizon:] - voucher[:-horizon]
    return float(np.sum(x * y) / np.sum(x * x))


def test_vouchers_follow_the_underlying_fair_value_not_its_quote_noise(calibrated_params):
    """Real voucher mids react to only part of LYCHEE's tick-level quote noise: their beta to it is attenuated at
    one tick and recovers over longer horizons."""
    lychee = calibrated_params.products["LYCHEE"]
    noisy = replace(
        calibrated_params,
        products=MappingProxyType({**calibrated_params.products, "LYCHEE": replace(lychee, quote_noise_sd=5.0)}),
    )

    day = generate_day(noisy, seed=1)

    assert _beta(day, "VOUCHER_6800", 1) < MAX_ONE_TICK_BETA_SHARE * _beta(day, "VOUCHER_6800", 100)


def test_tellurium_quotes_move_with_the_takers_that_hit_them(day_one):
    """Real TELLURIUM mids move ~2.8 the taker's way on the next tick after a chaser's order (the book is eaten)."""
    product = day_one.products["TELLURIUM"]
    ticks, first = np.unique(product.trade_ticks, return_index=True)
    sides = np.where(product.trade_prices[first] >= product.ask_prices[ticks, 0], 1.0, -1.0)
    inside = ticks < product.ticks - 1

    move = sides[inside] * (product.mid[ticks[inside] + 1] - product.mid[ticks[inside]])

    assert move.mean() > MIN_TELLURIUM_NEXT_TICK_IMPACT
