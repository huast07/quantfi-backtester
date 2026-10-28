from dataclasses import replace

import numpy as np
import pytest

from quantgen.generator.book import Book, BookParams, Layer, build_book
from quantgen.generator.takers import (
    BUY,
    SELL,
    ChaseFlow,
    IvRuleFlow,
    NoiseFlow,
    Orders,
    SizeDistribution,
    arrival_ticks,
    chase_book_adjustment,
    chase_orders,
    expect_chase,
    hit_touch,
    impact_path,
    iv_rule_tape,
    noise_tape,
    selective_intensity,
    sweep,
)

TICKS = 50_000


def flat_book(ticks: int, volume: int = 5) -> Book:
    layers = tuple(Layer(w, 0, 1.0, (volume,), (1.0,)) for w in (1.0, 3.0, 5.0))
    return build_book(np.full(ticks, 100.0), BookParams(layers=layers), np.random.default_rng(0))


def test_arrivals_without_clusters_follow_the_rate():
    ticks = arrival_ticks(np.random.default_rng(1), TICKS, 0.05)

    assert ticks.size / TICKS == pytest.approx(0.05, rel=0.05)


def test_clustered_arrivals_keep_the_rate_but_are_over_dispersed():
    plain = arrival_ticks(np.random.default_rng(2), TICKS, 0.05)
    bursty = arrival_ticks(np.random.default_rng(2), TICKS, 0.05, cluster_mean=3.0)

    def dispersion(ticks: np.ndarray) -> float:
        counts = np.bincount(ticks // 100, minlength=TICKS // 100)
        return counts.var() / counts.mean()

    assert bursty.size / TICKS == pytest.approx(0.05, rel=0.15)
    assert dispersion(bursty) > 2 * dispersion(plain)
    assert np.all(np.diff(bursty) > 0)


def test_touch_takers_trade_at_the_same_tick_touch_capped_by_its_volume():
    book = flat_book(3, volume=5)

    tape = hit_touch(book, np.array([0, 1, 2]), np.array([BUY, SELL, BUY]), np.array([2, 9, 5]))

    np.testing.assert_array_equal(tape.prices, [101.0, 99.0, 101.0])
    np.testing.assert_array_equal(tape.quantities, [2, 5, 5])


def test_sweeps_walk_the_book_printing_once_per_level():
    book = flat_book(1, volume=5)

    tape = sweep(book, np.array([0]), np.array([BUY]), np.array([12]))

    np.testing.assert_array_equal(tape.prices, [101.0, 103.0, 105.0])
    np.testing.assert_array_equal(tape.quantities, [5, 5, 2])


def test_noise_tape_matches_buy_probability_and_sizes():
    flow = NoiseFlow(rate=0.1, buy_prob=0.7, size=SizeDistribution((1, 2), (0.5, 0.5)))
    book = flat_book(TICKS)

    tape = noise_tape(flow, book, np.random.default_rng(3))

    assert np.mean(tape.prices == 101.0) == pytest.approx(0.7, abs=0.02)
    assert set(np.unique(tape.quantities)) == {1, 2}


def test_chase_adjustment_widens_both_sides_and_thins_only_the_jump_side():
    flow = ChaseFlow(
        base_rate=0.0,
        base_size=SizeDistribution((1,), (1.0,)),
        bin_ticks=10,
        order_prob=(0.5,),
        direction_prob=(0.9,),
        widen=(2.0,),
        thin=(0.25,),
        chase_size=SizeDistribution((10,), (1.0,)),
    )

    adjustment = chase_book_adjustment(flow, 30, np.array([5]), np.array([1.0]), np.random.default_rng(4))

    window = slice(5, 15)
    assert np.all(adjustment.widen[window] == 2.0)
    assert np.all(adjustment.widen[15:] == 0.0)
    assert np.all(adjustment.ask_scale[window] == 0.25)
    assert np.all(adjustment.bid_scale == 1.0)


def test_selective_intensity_keeps_the_average_rate_and_is_flat_without_selectivity():
    residual = np.random.default_rng(2).standard_normal(TICKS)

    assert np.array_equal(selective_intensity(residual, 0.0), np.ones(TICKS))
    assert selective_intensity(residual, 1.5).mean() == pytest.approx(1.0)


def test_selective_iv_takers_trade_when_the_mispricing_is_large():
    residual = np.random.default_rng(3).standard_normal(TICKS)
    flow = IvRuleFlow(rate=0.05, consistency=1.0, size=SizeDistribution((1,), (1.0,)), selectivity=1.0)

    tape = iv_rule_tape(flow, flat_book(TICKS), residual, np.random.default_rng(4))

    at_trades = np.abs(residual[tape.ticks]).mean() / np.abs(residual).mean()
    assert at_trades == pytest.approx(np.mean(residual**2) / np.mean(np.abs(residual)) ** 2, rel=0.05)
    assert tape.ticks.size / TICKS == pytest.approx(0.05, rel=0.1)
    assert np.all((residual[tape.ticks] < 0) == (tape.prices == 101.0))


def chase_flow(**changes) -> ChaseFlow:
    base = ChaseFlow(
        base_rate=0.0,
        base_size=SizeDistribution((1,), (1.0,)),
        bin_ticks=10,
        order_prob=(1.0, 1.0),
        direction_prob=(1.0, 1.0),
        widen=(0.0, 0.0),
        thin=(1.0, 1.0),
        chase_size=SizeDistribution((4,), (1.0,)),
    )
    return replace(base, **changes)


def test_chasers_order_in_the_jump_direction_inside_the_window_only():
    orders = chase_orders(chase_flow(), 100, np.array([50]), np.array([-1.0]), np.random.default_rng(5))

    np.testing.assert_array_equal(orders.ticks, np.arange(50, 70))
    assert np.all(orders.sides == SELL)
    assert np.all(orders.sizes == 4)


def test_expected_chase_volume_is_the_signed_mean_order_inside_the_window():
    flow = chase_flow(order_prob=(0.5, 0.2), direction_prob=(0.9, 0.6))

    expectation = expect_chase(flow, 100, np.array([50]), np.array([-1.0]))

    np.testing.assert_array_equal(np.flatnonzero(expectation.in_window), np.arange(50, 70))
    assert np.all(expectation.volume[:50] == 0.0)
    assert expectation.volume[55] == pytest.approx(-0.5 * 0.8 * 4)
    assert expectation.volume[65] == pytest.approx(-0.2 * 0.2 * 4)
    assert np.all(expectation.volume[70:] == 0.0)


def test_only_unexpected_flow_inside_a_chase_window_moves_the_quotes_along_the_kernel():
    flow = chase_flow(impact_knots=(1, 5), impact_per_lot=(0.5, 0.2), order_prob=(0.25, 0.0), direction_prob=(1.0, 1.0))
    expectation = expect_chase(flow, 40, np.array([10]), np.array([1.0]))
    orders = Orders(ticks=np.array([5, 10]), sides=np.array([SELL, BUY]), sizes=np.array([3, 4]))

    path = impact_path(flow, orders, expectation)

    surprise_at_order = 4 - 0.25 * 4
    assert np.all(path[:11] == 0.0)
    assert path[11] == pytest.approx(surprise_at_order * 0.5)
    assert path[13] == pytest.approx(surprise_at_order * 0.35 - 1 * 0.425 - 1 * 0.5)
    assert path[39] == pytest.approx(surprise_at_order * 0.2 - 9 * 0.2)


def test_no_impact_kernel_leaves_the_quotes_alone():
    orders = chase_orders(chase_flow(), 100, np.array([10]), np.array([1.0]), np.random.default_rng(5))

    expectation = expect_chase(chase_flow(), 100, np.array([10]), np.array([1.0]))

    assert np.all(impact_path(chase_flow(), orders, expectation) == 0.0)
