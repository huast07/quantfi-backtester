"""Calibration recovers known parameters from data generated with them, and runs on the real days."""

import numpy as np
import pytest

from quantgen.calibration.calibrate import calibrate, load_real_market_days, real_expiries
from quantgen.calibration.fit_book import fit_book
from quantgen.calibration.fit_flow import fit_noise_flow, fit_selectivity, rule_consistency
from quantgen.calibration.fit_processes import (
    find_jumps,
    fit_jump_dynamics,
    fit_mean_reverting_process,
    fit_random_walk_process,
    fit_steps,
)
from quantgen.calibration.variogram import fit_mean_reverting
from quantgen.generator.book import BookParams, Layer, build_book
from quantgen.generator.processes import (
    JumpDiffusion,
    JumpResponse,
    LocalTrend,
    MeanReverting,
    RandomWalk,
    Steps,
    ar1,
    jump_diffusion,
    mean_reverting,
    random_walk,
    steps,
)
from quantgen.generator.takers import (
    ChaseFlow,
    NoiseFlow,
    SizeDistribution,
    arrival_ticks,
    chase_orders,
    expect_chase,
    impact_path,
    noise_tape,
    selective_intensity,
    unexpected_volume,
)
from quantgen.market_day import ProductDay

TICKS = 10_000
DAYS = 6


def normals(seed: int) -> np.ndarray:
    return np.random.default_rng(seed).standard_normal(TICKS)


def product_day(center: np.ndarray, params: BookParams, flow: NoiseFlow | None, seed: int) -> ProductDay:
    rng = np.random.default_rng(seed)
    book = build_book(center, params, rng)
    tape = noise_tape(flow, book, rng) if flow else None
    empty = np.empty(0, dtype=np.int64)
    return ProductDay(
        book.bid_prices,
        book.bid_volumes,
        book.ask_prices,
        book.ask_volumes,
        tape.ticks if tape else empty,
        tape.prices if tape else empty.astype(float),
        tape.quantities if tape else empty,
    )


def test_random_walk_sigma_is_recovered():
    mids = [random_walk(RandomWalk(sigma=2.0), 1000.0, normals(seed)).path for seed in range(DAYS)]

    fit = fit_random_walk_process(mids)

    assert fit.sigma == pytest.approx(2.0, rel=0.1)


def test_mean_reverting_parameters_are_recovered():
    truth = MeanReverting(mean=500.0, kappa=0.01, sigma=1.0)
    mids = [mean_reverting(truth, 500.0, normals(seed)).path for seed in range(DAYS)]

    fit = fit_mean_reverting_process(mids)

    assert fit.mean == pytest.approx(500.0, abs=2.0)
    assert fit.kappa == pytest.approx(0.01, rel=0.4)
    assert fit.sigma == pytest.approx(1.0, rel=0.15)


def test_steps_and_their_absorbers_are_recovered():
    truth = Steps(daily_counts=(1,), step_sizes=(-100.0,), ramp_ticks=60, absorbers={})
    golden = [steps(truth, 8000.0, TICKS, np.random.default_rng(seed)).path for seed in range(DAYS)]
    noise = np.random.default_rng(99)
    white = [15000.0 - 0.6 * (g - 8000.0) + noise.normal(0, 0.5, TICKS) for g in golden]
    black = [12000.0 - 0.4 * (g - 8000.0) + noise.normal(0, 0.5, TICKS) for g in golden]

    fit = fit_steps(golden, {"WHITE": white, "BLACK": black})

    assert fit.daily_counts == (1,) * DAYS
    assert fit.step_sizes == pytest.approx((-100.0,) * DAYS, abs=1.0)
    assert fit.absorbers["WHITE"] == pytest.approx(0.6, abs=0.02)
    assert fit.absorbers["BLACK"] == pytest.approx(0.4, abs=0.02)


def test_jumps_above_the_threshold_are_found_with_their_tick_and_sign():
    mid = np.full(TICKS, 3000.0)
    mid[4000:] += 120.0
    mid[7000:] -= 90.0

    jumps = find_jumps(mid)

    np.testing.assert_array_equal(jumps.ticks, [4000, 7000])
    np.testing.assert_array_equal(np.sign(jumps.signs), [1, -1])


def test_book_layers_are_recovered():
    truth = BookParams(
        layers=(
            Layer(1.0, 1, 1.0, (10, 20), (0.5, 0.5)),
            Layer(4.0, 0, 0.8, (15,), (1.0,)),
            Layer(6.0, 0, 0.6, (25,), (1.0,)),
        )
    )
    days = [product_day(np.full(TICKS, 2000.0), truth, None, seed) for seed in range(3)]

    fit = fit_book(days)

    assert [layer.half_width for layer in fit.layers] == [1.0, 4.0, 6.0]
    assert [layer.jitter for layer in fit.layers] == [1, 0, 0]
    assert fit.layers[1].presence == pytest.approx(0.8, abs=0.03)
    assert fit.layers[2].presence == pytest.approx(0.6, abs=0.03)
    assert fit.layers[0].volumes == (10, 20)
    assert fit.inner is None


def test_noise_flow_rate_side_and_sizes_are_recovered():
    truth = NoiseFlow(rate=0.03, buy_prob=0.6, size=SizeDistribution((1, 2, 3), (0.2, 0.5, 0.3)))
    book = BookParams(layers=(Layer(2.0, 0, 1.0, (30,), (1.0,)),))
    days = [product_day(np.full(TICKS, 500.0), book, truth, seed) for seed in range(DAYS)]

    fit = fit_noise_flow(days)

    assert fit.rate == pytest.approx(0.03, rel=0.1)
    assert fit.buy_prob == pytest.approx(0.6, abs=0.04)
    assert fit.size.sizes == (1, 2, 3)
    assert fit.size.probs == pytest.approx((0.2, 0.5, 0.3), abs=0.04)


@pytest.mark.parametrize(("consistency", "agreement"), [(0.9, 0.8), (0.7, 0.95), (1.0, 0.75)])
def test_rule_consistency_undoes_sign_noise(consistency, agreement):
    measured = consistency * agreement + (1 - consistency) * (1 - agreement)

    assert rule_consistency(measured, agreement) == pytest.approx(consistency)


def test_rule_consistency_without_sign_information_is_a_coin_flip():
    assert rule_consistency(0.9, 0.5) == 0.5


def test_real_expiries_count_down_from_eight_days():
    assert real_expiries((-2, -1, 0)) == [8.0, 7.0, 6.0]


@pytest.mark.slow
def test_calibration_on_the_real_days(real_data_root):
    params = calibrate(load_real_market_days(real_data_root))

    golden = params.products["GOLDEN_PEARLS"].process
    assert len(params.products) == 26
    assert params.day == 1
    assert params.voucher_surface.days_to_expiry == pytest.approx(5.0)
    assert golden.daily_counts == (0, 1, 2)
    assert golden.step_sizes == (-100.0, -100.0, -50.0)
    assert golden.absorbers["WHITE_PEARLS"] + golden.absorbers["BLACK_PEARLS"] == pytest.approx(0.9, abs=0.1)
    np.linalg.cholesky(np.asarray(params.correlation.matrix))


@pytest.mark.parametrize("selectivity", [0.0, 0.7, 1.5])
def test_fit_selectivity_recovers_how_strongly_takers_wait_for_mispricing(selectivity):
    rng = np.random.default_rng(5)
    residuals = [rng.standard_normal(40_000) for _ in range(3)]
    trades = [arrival_ticks(rng, r.size, 0.05 * selective_intensity(r, selectivity)) for r in residuals]

    assert fit_selectivity(residuals, trades) == pytest.approx(selectivity, abs=0.15)


def test_noisy_ar1_residuals_are_recovered_with_their_noise():
    rng = np.random.default_rng(6)
    phi, sd, noise_sd = 0.99, 3.0, 0.5
    series = [
        ar1(rng.standard_normal(TICKS), phi, sd * np.sqrt(1 - phi**2)) + noise_sd * rng.standard_normal(TICKS)
        for _ in range(DAYS)
    ]

    fit = fit_mean_reverting(series)

    assert 1.0 - fit.kappa == pytest.approx(phi, abs=0.003)
    assert fit.sigma / np.sqrt(1 - phi**2) == pytest.approx(sd, rel=0.2)
    assert fit.noise_var == pytest.approx(noise_sd**2, rel=0.2)


def test_jump_response_and_taker_impact_are_separated_in_one_fit():
    response = JumpResponse(knots=(50, 200), drift=(10.0, 30.0), size_slope=(-0.5, -1.0), reference_size=150.0)
    process = JumpDiffusion(
        diffusion=LocalTrend(sigma=1.0, trend_sd=0.0, phi=0.0),
        jumps_per_day=5.0,
        jump_sizes=(100.0, 150.0, 200.0),
        direction_concentration=5.0,
        response=response,
    )
    flow = ChaseFlow(
        base_rate=0.01,
        base_size=SizeDistribution((2, 6), (0.5, 0.5)),
        bin_ticks=100,
        order_prob=(0.3, 0.1),
        direction_prob=(0.9, 0.7),
        widen=(0.0, 0.0),
        thin=(1.0, 1.0),
        chase_size=SizeDistribution((2, 6, 10), (0.4, 0.4, 0.2)),
        impact_knots=(1, 5, 20),
        impact_per_lot=(0.5, 0.3, 0.1),
    )
    mids, surprises = [], []
    for seed in range(30):
        fair = jump_diffusion(process, 5000.0, normals(seed), np.random.default_rng(seed))
        orders = chase_orders(flow, TICKS, fair.jump_ticks, fair.jump_signs, np.random.default_rng(100 + seed))
        expectation = expect_chase(flow, TICKS, fair.jump_ticks, fair.jump_signs)
        mids.append(fair.path + impact_path(flow, orders, expectation))
        surprises.append(unexpected_volume(orders, expectation))
    jumps = [find_jumps(mid) for mid in mids]

    fit = fit_jump_dynamics(mids, jumps, surprises, response.knots, flow.impact_knots)

    np.testing.assert_allclose(fit.response.drift, response.drift, atol=4.0)
    np.testing.assert_allclose(fit.response.size_slope, response.size_slope, atol=0.12)
    np.testing.assert_allclose(fit.impact_per_lot, flow.impact_per_lot, atol=0.05)
