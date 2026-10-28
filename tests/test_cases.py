import numpy as np
import pytest

from quantgen.cases.case import case_day, find_cases, load_catalog, parse_case
from quantgen.cases.context import CaseContext, event_shape
from quantgen.cases.param_modifiers import ScaleJumps
from quantgen.generator.market import generate_day
from quantgen.market_day import to_day_data
from quantgen.serde import SchemaError

SEED = 3


@pytest.fixture(scope="module")
def catalog():
    return load_catalog()


def test_catalog_has_forty_two_cases_across_three_tiers(catalog):
    tiers = [case.tier for case in catalog]
    assert len(catalog) == 42
    assert (tiers.count("observed"), tiers.count("plausible"), tiers.count("stress")) == (5, 28, 9)
    assert len({case.id for case in catalog}) == 42


def test_regular_day_case_is_exactly_the_generator_day(calibrated_params, catalog):
    (regular,) = find_cases(catalog, ["regular-day"])

    assert to_day_data(case_day(calibrated_params, regular, SEED)) == to_day_data(generate_day(calibrated_params, SEED))


def test_every_case_generates_a_valid_day(calibrated_params, catalog):
    for case in catalog:
        day = case_day(calibrated_params, case, SEED)
        for name, product in day.products.items():
            assert not np.isnan(product.mid).any(), (case.id, name)
            assert np.all(product.bid_prices[:, 0] < product.ask_prices[:, 0]), (case.id, name)


def test_case_days_are_deterministic_per_seed(calibrated_params, catalog):
    (crash,) = find_cases(catalog, ["black-swan-crash"])

    first = case_day(calibrated_params, crash, SEED)
    again = case_day(calibrated_params, crash, SEED)

    np.testing.assert_array_equal(first.products["LYCHEE"].mid, again.products["LYCHEE"].mid)


def test_black_swan_crash_drops_every_diffusive_product(calibrated_params, catalog):
    (crash,) = find_cases(catalog, ["black-swan-crash"])
    regular = generate_day(calibrated_params, SEED)

    crashed = case_day(calibrated_params, crash, SEED)

    for name in ("JELLY", "LYCHEE", "DRAGONFRUIT", "TOFFEE_CAKE"):
        gap = crashed.products[name].mid - regular.products[name].mid
        assert gap.min() < -0.03 * regular.products[name].mid[0], name


def test_wide_spreads_widen_every_book(calibrated_params, catalog):
    (wide,) = find_cases(catalog, ["wide-spreads"])
    regular = generate_day(calibrated_params, SEED)

    widened = case_day(calibrated_params, wide, SEED)

    for name, product in widened.products.items():
        spread = np.mean(product.ask_prices[:, 0] - product.bid_prices[:, 0])
        base = regular.products[name]
        assert spread > np.mean(base.ask_prices[:, 0] - base.bid_prices[:, 0]), name


def test_event_shape_ramps_holds_and_recovers():
    shape = event_shape(100, start=10, ramp=10, hold=10, recovery=0.5, recovery_ticks=10)

    assert shape[9] == 0.0
    assert shape[19] == pytest.approx(1.0)
    assert shape[29] == pytest.approx(1.0)
    assert shape[-1] == pytest.approx(0.5)


def test_bad_case_files_are_rejected_with_their_source():
    with pytest.raises(SchemaError, match="bad.yaml"):
        parse_case("id: x\ntitle: X\ntier: legendary\nfamily: f\nsummary: s\ndescription: d\n", "bad.yaml")
    with pytest.raises(SchemaError, match="bad.yaml"):
        parse_case(
            "id: x\ntitle: X\ntier: stress\nfamily: f\nsummary: s\ndescription: d\nmodifiers: [{kind: nope}]\n",
            "bad.yaml",
        )


def test_unknown_case_ids_are_reported(catalog):
    with pytest.raises(KeyError, match="no-such-case"):
        find_cases(catalog, ["regular-day", "no-such-case"])


def test_scaling_jump_sizes_scales_the_jump_response_with_them(calibrated_params):
    before = calibrated_params.products["TELLURIUM"].process.response
    modifier = ScaleJumps(products=("TELLURIUM",), size_factor=2.0)

    after = modifier.apply_params(calibrated_params, CaseContext("t", SEED, 0, 100, 50)).products["TELLURIUM"]

    assert after.process.response.reference_size == pytest.approx(2.0 * before.reference_size)
    np.testing.assert_allclose(after.process.response.drift, 2.0 * np.asarray(before.drift))
    assert after.process.response.size_slope == before.size_slope


def test_jumps_stick_case_removes_the_post_jump_response(calibrated_params):
    modifier = ScaleJumps(products=("TELLURIUM",), response_factor=0.0)

    after = modifier.apply_params(calibrated_params, CaseContext("t", SEED, 0, 100, 50)).products["TELLURIUM"]

    assert set(after.process.response.drift) == {0.0}
    assert set(after.process.response.size_slope) == {0.0}
