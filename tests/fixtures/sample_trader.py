from datamodel import Order, TradingState

LIMIT = 50


class Trader:
    def run(self, state: TradingState):
        result = {}
        for product, depth in state.order_depths.items():
            if not depth.buy_orders or not depth.sell_orders:
                continue
            bid, ask = max(depth.buy_orders), min(depth.sell_orders)
            pos = state.position.get(product, 0)
            limit = 20 if "PEARLS" in product else LIMIT
            orders = []
            if ask - bid >= 3:
                if pos < limit:
                    orders.append(Order(product, bid + 1, min(5, limit - pos)))
                if pos > -limit:
                    orders.append(Order(product, ask - 1, -min(5, limit + pos)))
            result[product] = orders
        return result, 0, ""
