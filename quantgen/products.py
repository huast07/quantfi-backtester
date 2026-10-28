"""The QuantiFi 2026 product universe and position limits, as listed on the wiki's Products tab."""

from types import MappingProxyType

VOUCHER_STRIKES: tuple[int, ...] = (6800, 7000, 7200, 7300, 7400, 7500, 7600, 7750, 7900, 8100)
VOUCHER_LIMIT = 50

_BASE_LIMITS = {
    "AMETHYST": 50,
    "TOFFEE_CAKE": 50,
    "PAPER_LANTERNS": 50,
    "TELLURIUM": 40,
    "JELLY": 50,
    "PEANUT_BUTTER": 50,
    "DRAGONFRUIT": 40,
    "GRANADILLA": 40,
    "MANGOSTEEN": 40,
    "FRUIT_BASKET": 40,
    "LYCHEE": 200,
    "WHITE_PEARLS": 20,
    "BLACK_PEARLS": 20,
    "GOLDEN_PEARLS": 20,
    "PINK_PEARLS": 20,
    "BLUE_PEARLS": 20,
}


def voucher_symbol(strike: int) -> str:
    """Symbol used in the data files (the wiki calls these LYCHEE_VOUCHERS_<strike>)."""
    return f"VOUCHER_{strike}"


PRODUCTS: tuple[str, ...] = tuple(sorted([*_BASE_LIMITS, *(voucher_symbol(k) for k in VOUCHER_STRIKES)]))

POSITION_LIMITS = MappingProxyType(
    {
        **_BASE_LIMITS,
        **{voucher_symbol(k): VOUCHER_LIMIT for k in VOUCHER_STRIKES},
        **{f"LYCHEE_VOUCHERS_{k}": VOUCHER_LIMIT for k in VOUCHER_STRIKES},
    }
)
