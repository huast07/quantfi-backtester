import numpy as np
import pytest

from quantgen.generator.book import MIN_PRICE, BookParams, InnerQuote, Layer, build_book, markov_switch

TICKS = 20_000


def layer(half_width: float, jitter: int = 0, presence: float = 1.0, volume: int = 10) -> Layer:
    return Layer(half_width, jitter, presence, (volume,), (1.0,))


def test_first_layer_must_always_be_present():
    with pytest.raises(ValueError, match="first book layer"):
        BookParams(layers=(layer(1.0, presence=0.9),))


def test_layers_inside_the_previous_jitter_are_rejected():
    with pytest.raises(ValueError, match="overlap"):
        BookParams(layers=(layer(1.0, jitter=2), layer(2.0)))


def test_full_book_has_ordered_levels_at_each_layer_width():
    params = BookParams(layers=(layer(1.0), layer(3.0), layer(5.0)))

    book = build_book(np.full(TICKS, 100.0), params, np.random.default_rng(0))

    assert np.all(book.bid_prices == [99.0, 97.0, 95.0])
    assert np.all(book.ask_prices == [101.0, 103.0, 105.0])
    assert np.all(book.bid_volumes == 10)


def test_jitter_pushes_quotes_out_by_zero_to_jitter_ticks():
    params = BookParams(layers=(layer(1.0, jitter=2),))

    book = build_book(np.full(TICKS, 100.0), params, np.random.default_rng(1))

    assert set(np.unique(book.ask_prices[:, 0])) == {101.0, 102.0, 103.0}
    assert set(np.unique(book.bid_prices[:, 0])) == {97.0, 98.0, 99.0}


def test_absent_layers_compact_so_the_next_present_layer_becomes_level_two():
    params = BookParams(layers=(layer(1.0), layer(3.0, presence=0.0), layer(5.0)))

    book = build_book(np.full(TICKS, 100.0), params, np.random.default_rng(2))

    assert np.all(book.bid_prices[:, 1] == 95.0)
    assert np.all(np.isnan(book.bid_prices[:, 2]))


def test_presence_sets_the_share_of_ticks_showing_a_layer():
    params = BookParams(layers=(layer(1.0), layer(3.0, presence=0.7)))

    book = build_book(np.full(TICKS, 100.0), params, np.random.default_rng(3))

    assert np.mean(~np.isnan(book.ask_prices[:, 1])) == pytest.approx(0.7, abs=0.02)


def test_quotes_never_go_below_the_minimum_price_near_zero_value():
    params = BookParams(layers=(layer(1.0), layer(3.0), layer(5.0)))

    book = build_book(np.linspace(-5.0, 4.0, TICKS), params, np.random.default_rng(4))

    shown = book.bid_prices[~np.isnan(book.bid_prices)]
    assert shown.min() >= MIN_PRICE
    assert np.all(book.bid_prices[:, 0] >= MIN_PRICE)


def test_widen_and_volume_scale_adjust_one_side():
    params = BookParams(layers=(layer(1.0, volume=20),))
    ticks = 10

    book = build_book(
        np.full(ticks, 100.0),
        params,
        np.random.default_rng(5),
        widen=np.full(ticks, 2.0),
        ask_scale=np.full(ticks, 0.25),
    )

    assert np.all(book.ask_prices[:, 0] == 103.0)
    assert np.all(book.ask_volumes[:, 0] == 5)
    assert np.all(book.bid_volumes[:, 0] == 20)


def test_markov_switch_spends_the_stationary_share_of_time_on():
    start, stay = 0.02, 0.8

    state = markov_switch(np.random.default_rng(6), 200_000, start, stay)

    assert state.mean() == pytest.approx(start / (1 - stay + start), rel=0.05)


def test_inner_quote_sits_inside_the_main_spread_when_on():
    inner = InnerQuote(start_prob=1.0, stay_prob=1.0, layer=layer(0.5))
    params = BookParams(layers=(layer(2.0), layer(4.0)), inner=inner)

    book = build_book(np.full(100, 100.0), params, np.random.default_rng(7))

    assert np.all(book.bid_prices[:, 0] == 100.0)
    assert np.all(book.ask_prices[:, 0] == 101.0)
    assert np.all(book.ask_prices[:, 1] == 102.0)
