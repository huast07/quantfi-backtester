"""Reference strategy: a plain market maker, used as the baseline for verdicts.

It is shipped as source and run exactly like an uploaded file, so it imports only `datamodel`. It quotes one tick
inside the spread when there is room (at the touch otherwise), a quarter of the position limit per side, and moves
both quotes one tick against its inventory once the position passes half the limit, so it leans towards flat.
It stays out of TELLURIUM and the vouchers: naive quoting there is run over by jump chasers and by the IV-rule
takers (it lost 13,000-44,000 a day on the real days), which would make beating the baseline meaningless.
"""

from datamodel import Order

LIMITS = {
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
SKIPPED = ("TELLURIUM",)
QUOTE_SHARE = 4
MIN_IMPROVING_SPREAD = 3


class Trader:
    def run(self, state):
        orders = {}
        for product, depth in state.order_depths.items():
            if product not in LIMITS or product in SKIPPED or not depth.buy_orders or not depth.sell_orders:
                continue
            limit = LIMITS[product]
            position = state.position.get(product, 0)
            best_bid, best_ask = max(depth.buy_orders), min(depth.sell_orders)
            improve = 1 if best_ask - best_bid >= MIN_IMPROVING_SPREAD else 0
            skew = -1 if position > limit // 2 else 1 if position < -limit // 2 else 0
            bid, ask = best_bid + improve + skew, best_ask - improve + skew
            if bid >= ask:
                continue
            size = max(limit // QUOTE_SHARE, 1)
            product_orders = []
            buy = min(size, limit - position)
            sell = min(size, limit + position)
            if buy > 0:
                product_orders.append(Order(product, bid, buy))
            if sell > 0:
                product_orders.append(Order(product, ask, -sell))
            orders[product] = product_orders
        return orders, 0, ""
