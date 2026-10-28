from dataclasses import replace

import numpy as np
import pytest

from quantgen.generator.processes import (
    JumpDiffusion,
    JumpResponse,
    LocalTrend,
    MeanReverting,
    RandomWalk,
    Steps,
    black_scholes_call,
    jump_diffusion,
    jump_response_path,
    local_trend,
    mean_reverting,
    random_walk,
    steps,
    trend_filter,
)

TICKS = 10_000


def normals(seed: int, ticks: int = TICKS) -> np.ndarray:
    return np.random.default_rng(seed).standard_normal(ticks)


def test_random_walk_tick_sd_is_sigma_and_starts_from_start():
    path = random_walk(RandomWalk(sigma=1.5), 100.0, normals(0, 100_000)).path

    assert np.std(np.diff(path)) == pytest.approx(1.5, rel=0.02)
    assert path[0] == pytest.approx(100.0, abs=10.0)


def test_mean_reverting_stays_near_its_mean():
    path = mean_reverting(MeanReverting(mean=500.0, kappa=0.05, sigma=1.0), 520.0, normals(1, 100_000)).path

    assert np.mean(path[1000:]) == pytest.approx(500.0, abs=1.0)
    assert np.std(path[1000:]) == pytest.approx(1.0 / np.sqrt(2 * 0.05), rel=0.15)


def test_local_trend_without_trend_is_a_random_walk():
    z = normals(2)
    process = LocalTrend(sigma=2.0, trend_sd=0.0, phi=0.9)

    trend = local_trend(process, 0.0, z).path
    walk = random_walk(RandomWalk(sigma=2.0), 0.0, z).path

    np.testing.assert_allclose(trend, walk)


def test_trend_filter_keeps_the_long_run_variance_of_a_trending_walk():
    process = LocalTrend(sigma=1.0, trend_sd=0.05, phi=0.98)
    c, tau = trend_filter(process)
    paths = [local_trend(process, 0.0, normals(seed, 50_000)).path for seed in range(4)]

    lag = 1000
    measured = np.mean([np.var(p[lag:] - p[:-lag]) for p in paths])

    assert c > 0 and tau > 0
    assert measured > lag * process.sigma**2


def test_one_step_per_day_ramps_by_the_step_size_and_then_stays_flat():
    process = Steps(daily_counts=(1,), step_sizes=(-100.0,), ramp_ticks=50, absorbers={})

    path = steps(process, 8000.0, TICKS, np.random.default_rng(3)).path

    moves = np.flatnonzero(np.diff(path))
    assert path.max() <= 8000.0
    assert path[-1] == pytest.approx(7900.0)
    assert moves.size <= 50
    assert np.all(np.diff(path) <= 0)


def test_step_count_is_drawn_from_the_observed_daily_counts():
    process = Steps(daily_counts=(0, 2), step_sizes=(10.0,), ramp_ticks=1, absorbers={})

    finals = {steps(process, 0.0, TICKS, np.random.default_rng(seed)).path[-1] for seed in range(30)}

    assert finals == {0.0, 20.0}


def test_jump_diffusion_marks_each_jump_and_moves_by_its_size():
    diffusion = LocalTrend(sigma=0.0, trend_sd=0.0, phi=0.0)
    process = JumpDiffusion(diffusion=diffusion, jumps_per_day=5.0, jump_sizes=(80.0,), direction_concentration=1.0)

    fair = jump_diffusion(process, 1000.0, normals(4), np.random.default_rng(4))

    increments = np.diff(fair.path)
    assert fair.jump_ticks.size > 0
    np.testing.assert_allclose(increments[fair.jump_ticks - 1], fair.jump_signs * 80.0)
    assert np.count_nonzero(increments) == fair.jump_ticks.size


RESPONSE = JumpResponse(knots=(10, 50), drift=(2.0, 6.0), size_slope=(-0.1, -0.5), reference_size=100.0)


def test_jump_response_follows_its_profile_from_each_jump_and_then_holds():
    path = jump_response_path(RESPONSE, 300, np.array([100]), np.array([-1.0]), np.array([110.0]))

    assert np.all(path[:101] == 0.0)
    assert path[110] == pytest.approx(-(2.0 - 0.1 * 10))
    assert path[130] == pytest.approx(-(4.0 - 0.3 * 10))
    assert path[150] == pytest.approx(-(6.0 - 0.5 * 10))
    assert np.all(path[150:] == path[150])


def test_jump_diffusion_adds_the_response_to_every_jump():
    diffusion = LocalTrend(sigma=0.0, trend_sd=0.0, phi=0.0)
    bare = JumpDiffusion(diffusion=diffusion, jumps_per_day=5.0, jump_sizes=(80.0,), direction_concentration=1.0)

    plain = jump_diffusion(bare, 1000.0, normals(4), np.random.default_rng(4))
    responding = jump_diffusion(replace(bare, response=RESPONSE), 1000.0, normals(4), np.random.default_rng(4))

    sizes = np.full(plain.jump_ticks.size, 80.0)
    expected = jump_response_path(RESPONSE, TICKS, plain.jump_ticks, plain.jump_signs, sizes)
    np.testing.assert_allclose(responding.path - plain.path, expected)


def test_black_scholes_call_respects_no_arbitrage_bounds():
    spot = np.full(5, 7500.0)
    strikes = np.array([7000, 7250, 7500, 7750, 8000])
    days = np.full(5, 5.0)
    vol = np.full(5, 0.01)

    prices = np.array(
        [black_scholes_call(spot[i : i + 1], k, days[i : i + 1], vol[i : i + 1])[0] for i, k in enumerate(strikes)]
    )

    assert np.all(prices >= np.maximum(spot - strikes, 0.0) - 1e-9)
    assert np.all(prices <= spot)
    assert np.all(np.diff(prices) < 0)
