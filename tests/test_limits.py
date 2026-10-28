import prosperity3bt.data as p3data

from quantgen.adapter.limits import quantifi_limits
from quantgen.products import POSITION_LIMITS, PRODUCTS


def test_wiki_position_limits_cover_all_26_products():
    assert len(PRODUCTS) == 26
    assert POSITION_LIMITS["AMETHYST"] == 50
    assert POSITION_LIMITS["TELLURIUM"] == 40
    assert POSITION_LIMITS["LYCHEE"] == 200
    assert POSITION_LIMITS["PINK_PEARLS"] == 20
    assert POSITION_LIMITS["VOUCHER_7750"] == 50


def test_voucher_limits_are_registered_under_both_wiki_and_data_names():
    assert POSITION_LIMITS["LYCHEE_VOUCHERS_7750"] == POSITION_LIMITS["VOUCHER_7750"] == 50


def test_limits_are_registered_inside_the_context_and_restored_after():
    before = dict(p3data.LIMITS)
    assert "AMETHYST" not in before

    with quantifi_limits():
        assert p3data.LIMITS["AMETHYST"] == 50
        assert p3data.LIMITS["LYCHEE"] == 200

    assert p3data.LIMITS == before


def test_limits_are_restored_even_when_the_body_raises():
    before = dict(p3data.LIMITS)
    try:
        with quantifi_limits():
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert p3data.LIMITS == before
